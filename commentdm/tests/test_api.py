from __future__ import annotations

import services
from database import SessionLocal
from instagram import InstagramError
from models import Campaign
from tests.fakes import FakeInstagramClient

POST_ID = "17895695668004550"
IG_ID = "17841400000000000"
TOKEN = "EAAG" + "x" * 48


def campaign_payload(**overrides):
    values = {
        "name": "Pricing reel",
        "post_id": POST_ID,
        "keywords": "price, cost, how much",
        "comment_reply": "Sent you a DM!",
        "dm_message": "Here is the price list.",
        "is_active": True,
    }
    values.update(overrides)
    return values


def create_campaign(client, **overrides):
    response = client.post("/api/campaigns", json=campaign_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def save_credentials(client):
    return client.put(
        "/api/config",
        json={
            "access_token": TOKEN,
            "instagram_business_account_id": IG_ID,
            "page_id": "100000000000000",
        },
    )


def test_campaign_crud_and_validation(client):
    created = create_campaign(client)
    assert created["name"] == "Pricing reel"
    assert created["keyword_list"] == ["price", "cost", "how much"]
    campaign_id = created["id"]

    listed = client.get("/api/campaigns").json()["items"]
    assert [campaign["id"] for campaign in listed] == [campaign_id]

    updated = client.put(
        f"/api/campaigns/{campaign_id}",
        json=campaign_payload(name="Updated", keywords="guide,GUIDE, freebie ", is_active=False),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated"
    assert updated.json()["keywords"] == "guide, freebie"
    assert updated.json()["is_active"] is False

    toggled = client.post(f"/api/campaigns/{campaign_id}/toggle")
    assert toggled.status_code == 200
    assert toggled.json()["is_active"] is True

    assert client.delete(f"/api/campaigns/{campaign_id}").status_code == 204
    assert client.get(f"/api/campaigns/{campaign_id}").status_code == 404
    assert client.get("/api/campaigns").json()["items"] == []


def test_campaign_validation_messages(client):
    bad_post = client.post("/api/campaigns", json=campaign_payload(post_id="reel-123"))
    assert bad_post.status_code == 422
    assert "numeric" in bad_post.json()["detail"]

    no_keywords = client.post("/api/campaigns", json=campaign_payload(keywords=" , "))
    assert no_keywords.status_code == 422
    assert "keyword" in no_keywords.json()["detail"].lower()

    too_long = client.post(
        "/api/campaigns", json=campaign_payload(dm_message="x" * 1001)
    )
    assert too_long.status_code == 422


def test_campaign_creation_caches_post_preview(client, monkeypatch):
    monkeypatch.setattr(services, "build_client", lambda db: FakeInstagramClient())
    created = create_campaign(client, name=None)
    assert created["post_thumbnail_url"] == "https://cdn.example.test/thumb.jpg"
    assert created["post_caption"] == "A reel about pricing"
    assert created["post_permalink"] == "https://www.instagram.com/p/abc/"
    # No name supplied → derived from the caption.
    assert created["name"].startswith("A reel about pricing")


def test_config_never_returns_the_raw_token(client):
    response = save_credentials(client)
    assert response.status_code == 200
    data = response.json()
    assert data["has_access_token"] is True
    assert data["token_source"] == "database"
    assert data["access_token_masked"].endswith(TOKEN[-4:])
    assert "access_token" not in data
    assert TOKEN not in response.text

    fetched = client.get("/api/config")
    assert fetched.status_code == 200
    assert TOKEN not in fetched.text
    assert fetched.json()["access_token_masked"] == data["access_token_masked"]


def test_config_update_and_clear_token(client):
    save_credentials(client)
    updated = client.put("/api/config", json={"page_id": "100000000000001"})
    assert updated.json()["page_id"] == "100000000000001"
    assert updated.json()["has_access_token"] is True

    cleared = client.put("/api/config", json={"clear_access_token": True})
    assert cleared.json()["has_access_token"] is False
    assert cleared.json()["access_token_masked"] is None


def test_config_rejects_non_numeric_ids(client):
    response = client.put("/api/config", json={"instagram_business_account_id": "abc"})
    assert response.status_code == 422


def test_connection_test_and_subscribe(client, monkeypatch):
    save_credentials(client)
    monkeypatch.setattr(services, "build_client", lambda db: FakeInstagramClient())

    tested = client.post("/api/config/test")
    assert tested.status_code == 200
    assert tested.json()["account"]["username"] == "fawziko.studio"
    assert client.get("/api/config").json()["instagram_username"] == "fawziko.studio"

    subscribed = client.post("/api/config/subscribe")
    assert subscribed.status_code == 200
    assert subscribed.json()["subscribed_fields"] == ["comments", "messages"]


def test_refresh_token_requires_app_credentials(client):
    save_credentials(client)
    response = client.post("/api/config/refresh-token")
    assert response.status_code == 400
    assert "INSTAGRAM_APP_ID" in response.json()["detail"]


def test_simulate_campaign(client):
    campaign = create_campaign(client)
    campaign_id = campaign["id"]

    miss = client.post(
        f"/api/campaigns/{campaign_id}/simulate", json={"comment_text": "love this"}
    )
    assert miss.status_code == 400

    hit = client.post(
        f"/api/campaigns/{campaign_id}/simulate",
        json={"comment_text": "What is the PRICE?", "commenter_username": "@lina.creates"},
    )
    assert hit.status_code == 200
    payload = hit.json()
    assert payload["matched_keyword"] == "price"
    assert payload["comment_reply"] == "Sent you a DM!"
    assert payload["dm_message"] == "Here is the price list."
    assert payload["activity"]["status"] == "simulated"
    assert payload["activity"]["commenter_username"] == "lina.creates"

    stats = client.get("/api/stats").json()
    assert stats["simulations"] == 1
    assert stats["comments_matched"] == 0


def test_activity_list_filters_and_clear(client):
    campaign = create_campaign(client)
    campaign_id = campaign["id"]
    for text in ("price", "cost"):
        client.post(f"/api/campaigns/{campaign_id}/simulate", json={"comment_text": text})

    items = client.get("/api/activity").json()["items"]
    assert len(items) == 2

    filtered = client.get("/api/activity", params={"campaign_id": campaign_id}).json()
    assert len(filtered["items"]) == 2

    assert client.get("/api/activity", params={"status": "success"}).json()["items"] == []

    cleared = client.delete("/api/activity")
    assert cleared.json()["deleted"] == 2
    assert client.get("/api/activity").json()["items"] == []


def test_deleting_a_campaign_keeps_activity_and_clears_fk(client):
    campaign = create_campaign(client)
    campaign_id = campaign["id"]
    client.post(f"/api/campaigns/{campaign_id}/simulate", json={"comment_text": "price"})

    assert client.delete(f"/api/campaigns/{campaign_id}").status_code == 204
    items = client.get("/api/activity").json()["items"]
    assert len(items) == 1
    assert items[0]["campaign_id"] is None
    assert items[0]["campaign_name"] == "Deleted campaign"


def test_demo_seed_only_when_empty(client):
    seeded = client.post("/api/demo/seed")
    assert seeded.status_code == 200
    assert seeded.json()["campaigns"] == 2
    assert seeded.json()["activity"] == 3

    again = client.post("/api/demo/seed")
    assert again.status_code == 409

    campaigns = client.get("/api/campaigns").json()["items"]
    assert len(campaigns) == 2
    assert all(campaign["name"].startswith("Sample —") for campaign in campaigns)
    activity = client.get("/api/activity").json()["items"]
    assert {item["status"] for item in activity} == {"simulated"}


def test_post_preview_requires_credentials(client):
    response = client.post("/api/posts/preview", json={"post_id": POST_ID})
    assert response.status_code == 400
    assert "access token" in response.json()["detail"].lower()


def test_post_preview_with_client(client, monkeypatch):
    monkeypatch.setattr(services, "build_client", lambda db: FakeInstagramClient())
    response = client.post("/api/posts/preview", json={"post_id": POST_ID})
    assert response.status_code == 200
    assert response.json()["thumbnail_url"] == "https://cdn.example.test/thumb.jpg"
    assert response.json()["cached"] is False


def test_post_preview_falls_back_to_cache(client, monkeypatch):
    with SessionLocal() as db:
        db.add(
            Campaign(
                name="Cached",
                post_id=POST_ID,
                keywords="price",
                comment_reply="hi",
                dm_message="hello",
                post_thumbnail_url="https://cdn.example.test/cached.jpg",
                post_caption="Cached caption",
                post_permalink="https://instagram.com/p/cached/",
            )
        )
        db.commit()

    class FailingClient(FakeInstagramClient):
        async def get_post_details(self, post_id):
            raise InstagramError("Media not found", status_code=400, code=100)

    monkeypatch.setattr(services, "build_client", lambda db: FailingClient())
    response = client.post("/api/posts/preview", json={"post_id": POST_ID})
    assert response.status_code == 200
    assert response.json()["cached"] is True
    assert response.json()["thumbnail_url"] == "https://cdn.example.test/cached.jpg"
    assert "Media not found" in response.json()["warning"]


def test_stats_endpoint(client):
    campaign = create_campaign(client)
    client.post(f"/api/campaigns/{campaign['id']}/simulate", json={"comment_text": "price"})
    stats = client.get("/api/stats").json()
    assert stats["campaigns_total"] == 1
    assert stats["campaigns_active"] == 1
    assert stats["simulations"] == 1
    assert stats["comments_matched"] == 0
    assert stats["success_rate"] == 0
