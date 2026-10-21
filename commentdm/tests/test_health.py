from __future__ import annotations


def test_health_returns_exact_payload(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_alias(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_dashboard_pages_render(client):
    for path in ("/dashboard", "/dashboard/activity", "/dashboard/settings"):
        response = client.get(path)
        assert response.status_code == 200
        assert "CommentDM" in response.text


def test_root_redirects_to_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/dashboard"


def test_security_headers_do_not_block_iframe_previews(client):
    response = client.get("/dashboard")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "script-src 'self'" in response.headers["content-security-policy"]
    # The dashboard must stay embeddable by the hosted preview/proxy.
    assert "x-frame-options" not in response.headers
    assert "frame-ancestors" not in response.headers["content-security-policy"]


def test_api_validation_error_is_readable(client):
    response = client.post(
        "/api/campaigns",
        json={
            "post_id": "not-numeric",
            "keywords": "price",
            "comment_reply": "hi",
            "dm_message": "hello",
        },
    )
    assert response.status_code == 422
    assert "post_id" in response.json()["detail"]
    assert "numeric" in response.json()["detail"]
