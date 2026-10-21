from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

import services
from database import SessionLocal
from instagram import InstagramError
from models import Campaign, Config, ProcessedComment
from tests.fakes import FakeInstagramClient, already_sent_error

POST_ID = "17895695668004550"
IG_ID = "17841400000000000"
TOKEN = "EAAG-test-token"


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeInstagramClient.instances.clear()
    yield
    FakeInstagramClient.instances.clear()


def add_campaign(db, **overrides):
    values = {
        "name": "Pricing",
        "post_id": POST_ID,
        "keywords": "price, how much",
        "comment_reply": "Sent you a DM!",
        "dm_message": "Here is the price list.",
        "is_active": True,
    }
    values.update(overrides)
    campaign = Campaign(**values)
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def add_credentials(db):
    db.add(
        Config(
            id=1,
            access_token=TOKEN,
            instagram_business_account_id=IG_ID,
            page_id="100000000000000",
        )
    )
    db.commit()


def process(db, **overrides):
    values = {
        "comment_id": "comment_1",
        "text": "Can I get the price please?",
        "post_id": POST_ID,
        "commenter_id": "987654321",
        "commenter_username": "lina.creates",
    }
    values.update(overrides)
    return asyncio.run(services.process_comment(db, **values))


def test_longest_keyword_and_active_filter():
    with SessionLocal() as db:
        add_campaign(db)
        add_campaign(db, name="Inactive", keywords="cost", is_active=False)
        campaign, keyword = services.find_matching_campaign(db, POST_ID, "how much does it cost?")
        assert campaign is not None
        assert keyword == "how much"

        # The inactive campaign must not match.
        assert services.find_matching_campaign(db, POST_ID, "cost only") == (None, None)
        # Wrong post.
        assert services.find_matching_campaign(db, "999", "price") == (None, None)


def test_process_comment_success_and_dedupe(monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)
    with SessionLocal() as db:
        campaign = add_campaign(db)
        add_credentials(db)

        record = process(db)
        assert record is not None
        assert record.status == "success"
        assert record.comment_reply_status == "sent"
        assert record.dm_status == "sent"
        assert record.matched_keyword == "price"

        duplicate = process(db)
        assert duplicate is None

        count = db.scalar(select(func.count(ProcessedComment.id)))
        assert count == 1
        db.refresh(campaign)
        assert campaign.times_triggered == 1
        assert campaign.last_triggered_at is not None

        fake = FakeInstagramClient.instances[0]
        assert [call[0] for call in fake.calls] == ["reply_to_comment", "send_private_reply"]


def test_process_comment_ignores_non_matching_comment(monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)
    with SessionLocal() as db:
        add_campaign(db)
        add_credentials(db)
        assert process(db, text="love this shot") is None
        assert db.scalar(select(func.count(ProcessedComment.id))) == 0


def test_process_comment_without_credentials_logs_failure(monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)
    with SessionLocal() as db:
        add_campaign(db)
        record = process(db)
        assert record is not None
        assert record.status == "failed"
        assert "access token" in (record.error_detail or "").lower()
        # Campaign match is still counted.
        campaign = db.scalar(select(Campaign))
        assert campaign.times_triggered == 1


def test_already_sent_private_reply_is_reported(monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)
    with SessionLocal() as db:
        add_campaign(db)
        add_credentials(db)
        monkeypatch.setattr(
            FakeInstagramClient,
            "send_private_reply",
            _raise_private(already_sent_error()),
        )
        record = process(db)
        assert record is not None
        assert record.comment_reply_status == "sent"
        assert record.dm_status == "already_sent"
        assert record.status == "success"
        assert "already sent" in (record.error_detail or "").lower()


def test_dm_falls_back_to_existing_conversation(monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)

    async def fail_private(self, comment_id, message):
        raise InstagramError("Private reply not available", status_code=400, code=100)

    monkeypatch.setattr(FakeInstagramClient, "send_private_reply", fail_private)
    with SessionLocal() as db:
        add_campaign(db)
        add_credentials(db)
        record = process(db)
        assert record is not None
        assert record.dm_status == "sent"
        assert record.status == "success"
        assert "delivered via the existing DM conversation" in (record.error_detail or "")
        assert any(call[0] == "send_dm" for call in FakeInstagramClient.instances[0].calls)


def test_public_reply_failure_marks_partial(monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)

    async def fail_reply(self, comment_id, message):
        raise InstagramError("Reply blocked", status_code=400, code=10)

    monkeypatch.setattr(FakeInstagramClient, "reply_to_comment", fail_reply)
    with SessionLocal() as db:
        add_campaign(db)
        add_credentials(db)
        record = process(db)
        assert record is not None
        assert record.comment_reply_status == "failed"
        assert record.dm_status == "sent"
        assert record.status == "partial"
        assert "Public reply failed" in (record.error_detail or "")


def test_simulation_does_not_call_api_and_does_not_count(monkeypatch):
    monkeypatch.setattr(services, "InstagramClient", FakeInstagramClient)
    with SessionLocal() as db:
        campaign = add_campaign(db)
        record = services.simulate_campaign(db, campaign, "PRICE please", "lina")
        assert record.status == "simulated"
        assert record.matched_keyword == "price"
        assert FakeInstagramClient.instances == []
        db.refresh(campaign)
        assert campaign.times_triggered == 0

        with pytest.raises(ValueError):
            services.simulate_campaign(db, campaign, "nice photo", None)


def test_parse_comment_events_skips_replies_and_self_comments():
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": IG_ID,
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": "c1",
                            "text": "price",
                            "media": {"id": POST_ID},
                            "from": {"id": "user-1", "username": "lina"},
                        },
                    },
                    {
                        "field": "comments",
                        "value": {
                            "id": "c2",
                            "text": "price",
                            "parent_id": "c1",
                            "media": {"id": POST_ID},
                            "from": {"id": "user-2", "username": "omar"},
                        },
                    },
                    {
                        "field": "comments",
                        "value": {
                            "id": "c3",
                            "text": "our own comment",
                            "media": {"id": POST_ID},
                            "from": {"id": IG_ID, "username": "business"},
                        },
                    },
                    {"field": "mentions", "value": {"id": "ignored"}},
                ],
            }
        ],
    }
    events = services.parse_comment_events(payload)
    assert [event["comment_id"] for event in events] == ["c1"]
    assert events[0]["post_id"] == POST_ID
    assert events[0]["commenter_username"] == "lina"
    assert events[0]["account_id"] == IG_ID


def test_parse_comment_events_tolerates_malformed_payloads():
    assert services.parse_comment_events(None) == []
    assert services.parse_comment_events({}) == []
    assert services.parse_comment_events({"entry": [None, {"changes": [None]}]}) == []


def _raise_private(error):
    async def inner(self, comment_id, message):
        raise error

    return inner
