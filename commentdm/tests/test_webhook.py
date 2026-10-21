from __future__ import annotations

import json
from dataclasses import replace

import pytest
from sqlalchemy import func, select

import services
from config import get_settings
from database import SessionLocal
from models import Campaign, Config, ProcessedComment
from routes import webhook as webhook_routes
from security import compute_signature
from tests.fakes import FakeInstagramClient

SECRET = "test-app-secret"
IG_ID = "17841400000000000"
POST_ID = "17895695668004550"


def build_payload(
    *,
    comment_id="comment_1",
    text="price please",
    post_id=POST_ID,
    author_id="987654321",
    username="lina.creates",
    parent_id=None,
    account_id=IG_ID,
    field="comments",
):
    value = {
        "id": comment_id,
        "text": text,
        "media": {"id": post_id},
        "from": {"id": author_id, "username": username},
    }
    if parent_id:
        value["parent_id"] = parent_id
    return {
        "object": "instagram",
        "entry": [
            {
                "id": account_id,
                "time": 1790000000,
                "changes": [{"field": field, "value": value}],
            }
        ],
    }


def post_webhook(client, payload, *, signature=True):
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}
    if signature:
        headers["X-Hub-Signature-256"] = compute_signature(SECRET, body)
    return client.post("/webhook/instagram", content=body, headers=headers)


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeInstagramClient.instances.clear()
    yield
    FakeInstagramClient.instances.clear()


def seed_campaign_and_credentials():
    with SessionLocal() as db:
        db.add(
            Config(
                id=1,
                access_token="EAAG-test-token",
                instagram_business_account_id=IG_ID,
                page_id="100000000000000",
            )
        )
        db.add(
            Campaign(
                name="Pricing",
                post_id=POST_ID,
                keywords="price, how much",
                comment_reply="Sent you a DM!",
                dm_message="Here is the price list.",
                is_active=True,
            )
        )
        db.commit()


def test_webhook_verification_challenge(client):
    response = client.get(
        "/webhook/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-verify-token",
            "hub.challenge": "1158201444",
        },
    )
    assert response.status_code == 200
    assert response.text == "1158201444"
    assert response.headers["content-type"].startswith("text/plain")


def test_webhook_verification_rejects_wrong_token(client):
    response = client.get(
        "/webhook/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "1158201444",
        },
    )
    assert response.status_code == 403


def test_webhook_requires_valid_signature(client):
    body = json.dumps(build_payload()).encode()
    unsigned = client.post(
        "/webhook/instagram", content=body, headers={"content-type": "application/json"}
    )
    assert unsigned.status_code == 403

    bad = client.post(
        "/webhook/instagram",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
        },
    )
    assert bad.status_code == 403


def test_webhook_handles_missing_app_secret(monkeypatch, client):
    settings = replace(get_settings(), facebook_app_secret="", allow_unsigned_webhooks=False)
    monkeypatch.setattr(webhook_routes, "get_settings", lambda: settings)
    response = client.post("/webhook/instagram", json=build_payload())
    assert response.status_code == 503


def test_webhook_can_explicitly_allow_unsigned_payloads(monkeypatch, client):
    settings = replace(
        get_settings(), facebook_app_secret="", allow_unsigned_webhooks=True
    )
    monkeypatch.setattr(webhook_routes, "get_settings", lambda: settings)
    response = client.post("/webhook/instagram", json=build_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "received"


def test_webhook_queues_matching_comment(client, monkeypatch):
    captured = []

    async def fake_process(db, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(services, "process_comment", fake_process)
    response = post_webhook(client, build_payload())
    assert response.status_code == 200
    assert response.json() == {"status": "received", "queued": 1}
    assert captured[0]["comment_id"] == "comment_1"
    assert captured[0]["text"] == "price please"
    assert captured[0]["post_id"] == POST_ID
    assert captured[0]["commenter_username"] == "lina.creates"


def test_webhook_ignores_replies_and_self_comments(client, monkeypatch):
    captured = []

    async def fake_process(db, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(services, "process_comment", fake_process)

    reply = post_webhook(client, build_payload(comment_id="c2", parent_id="c1"))
    assert reply.json()["queued"] == 0

    own = post_webhook(client, build_payload(comment_id="c3", author_id=IG_ID))
    assert own.json()["queued"] == 0

    assert captured == []


def test_webhook_ignores_other_accounts(client, monkeypatch):
    captured = []

    async def fake_process(db, **kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(services, "process_comment", fake_process)
    seed_campaign_and_credentials()
    response = post_webhook(
        client, build_payload(comment_id="c9", account_id="999999999999999")
    )
    assert response.json()["queued"] == 0
    assert captured == []


def test_webhook_ignores_non_comment_fields(client):
    response = post_webhook(client, build_payload(field="mentions"))
    assert response.status_code == 200
    assert response.json()["queued"] == 0


def test_webhook_returns_400_for_malformed_json(client):
    body = b"{not-json"
    response = client.post(
        "/webhook/instagram",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": compute_signature(SECRET, body),
        },
    )
    assert response.status_code == 400


def test_webhook_end_to_end_deduplicates(client, monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)
    seed_campaign_and_credentials()

    first = post_webhook(client, build_payload())
    assert first.status_code == 200
    assert first.json()["queued"] == 1

    # Meta may retry the same event; the unique comment_id must absorb it.
    second = post_webhook(client, build_payload())
    assert second.status_code == 200
    assert second.json()["queued"] == 1

    with SessionLocal() as db:
        assert db.scalar(select(func.count(ProcessedComment.id))) == 1
        record = db.scalar(select(ProcessedComment))
        assert record.status == "success"
        assert record.dm_message_id == "mid_123"
        campaign = db.scalar(select(Campaign))
        assert campaign.times_triggered == 1

    assert len(FakeInstagramClient.instances) == 1
    assert [call[0] for call in FakeInstagramClient.instances[0].calls] == [
        "reply_to_comment",
        "send_private_reply",
    ]
