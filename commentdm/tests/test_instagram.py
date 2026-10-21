from __future__ import annotations

import asyncio
import json
import urllib.parse

import httpx
import pytest

from instagram import InstagramClient, InstagramConfigError, InstagramError


def run(coro):
    return asyncio.run(coro)


def make_client(handler, *, retries=0, token="test-token", account="17841400000000000"):
    calls: list[dict] = []
    sleeps: list[float] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "path": request.url.path,
                "query": dict(request.url.params),
                "body": request.content,
                "headers": dict(request.headers),
            }
        )
        return handler(request)

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = InstagramClient(
        token,
        account_id=account,
        max_retries=retries,
        transport=httpx.MockTransport(wrapped),
        sleep=fake_sleep,
    )
    return client, calls, sleeps


def test_client_requires_token():
    with pytest.raises(InstagramConfigError):
        InstagramClient("")


def test_reply_to_comment_posts_message():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        form = urllib.parse.parse_qs(request.content.decode())
        assert form["message"] == ["Thanks for commenting!"]
        assert request.url.params["access_token"] == "test-token"
        return httpx.Response(200, json={"id": "reply_42"})

    client, calls, _ = make_client(handler)

    async def go():
        async with client:
            return await client.reply_to_comment("comment_1", "Thanks for commenting!")

    result = run(go())
    assert result == {"id": "reply_42"}
    assert calls[0]["path"] == "/v23.0/comment_1/replies"


def test_private_reply_addresses_comment_in_json():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["recipient"] == {"comment_id": "comment_1"}
        assert payload["message"] == {"text": "Here is your guide"}
        return httpx.Response(200, json={"message_id": "mid_1", "recipient_id": "42"})

    client, calls, _ = make_client(handler)

    async def go():
        async with client:
            return await client.send_private_reply("comment_1", "Here is your guide")

    result = run(go())
    assert result == {"message_id": "mid_1", "recipient_id": "42"}
    assert calls[0]["path"] == "/v23.0/17841400000000000/messages"


def test_standard_dm_addresses_user_id():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["recipient"] == {"id": "987654321"}
        return httpx.Response(200, json={"message_id": "mid_2"})

    client, _, _ = make_client(handler)

    async def go():
        async with client:
            return await client.send_dm("987654321", "hello")

    assert run(go())["message_id"] == "mid_2"


def test_missing_account_id_blocks_dm():
    client = InstagramClient("token", transport=httpx.MockTransport(lambda r: httpx.Response(500)))

    async def go():
        async with client:
            await client.send_private_reply("c", "hello")

    with pytest.raises(InstagramConfigError):
        run(go())


def test_get_post_details_prefers_thumbnail_for_video():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "thumbnail_url" in request.url.params["fields"]
        return httpx.Response(
            200,
            json={
                "id": "123",
                "caption": "Reel caption",
                "media_type": "VIDEO",
                "media_url": "https://video.example/file.mp4",
                "thumbnail_url": "https://img.example/thumb.jpg",
                "permalink": "https://instagram.com/p/x/",
            },
        )

    client, _, _ = make_client(handler)

    async def go():
        async with client:
            return await client.get_post_details("123")

    details = run(go())
    assert details["thumbnail_url"] == "https://img.example/thumb.jpg"
    assert details["caption"] == "Reel caption"


def test_get_post_details_uses_media_url_for_images():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "123",
                "media_type": "IMAGE",
                "media_url": "https://img.example/photo.jpg",
            },
        )

    client, _, _ = make_client(handler)

    async def go():
        async with client:
            return await client.get_post_details("123")

    assert run(go())["thumbnail_url"] == "https://img.example/photo.jpg"


def test_rate_limit_is_retried_with_backoff():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                429,
                json={"error": {"message": "Calls to this api have exceeded the rate limit.", "code": 613}},
            )
        return httpx.Response(200, json={"id": "reply_1"})

    client, _, sleeps = make_client(handler, retries=2)

    async def go():
        async with client:
            return await client.reply_to_comment("c1", "hi")

    assert run(go()) == {"id": "reply_1"}
    assert attempts["count"] == 2
    assert len(sleeps) == 1 and sleeps[0] >= 1.0


def test_rate_limit_eventually_raises_flagged_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "Rate limited", "code": 613, "fbtrace_id": "trace1"}},
        )

    client, calls, sleeps = make_client(handler, retries=1)

    async def go():
        async with client:
            await client.reply_to_comment("c1", "hi")

    with pytest.raises(InstagramError) as excinfo:
        run(go())
    assert excinfo.value.is_rate_limit is True
    assert excinfo.value.retryable is True
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_graph_error_includes_code_but_never_the_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Unsupported post request.",
                    "code": 100,
                    "error_subcode": 33,
                    "error_user_msg": "This post does not exist.",
                    "fbtrace_id": "abc",
                }
            },
        )

    client, _, _ = make_client(handler)

    async def go():
        async with client:
            await client.get_post_details("999")

    with pytest.raises(InstagramError) as excinfo:
        run(go())
    error = excinfo.value
    assert error.code == 100
    assert error.subcode == 33
    assert error.retryable is False
    message = error.public_message()
    assert "This post does not exist." in message
    assert "code 100" in message
    assert "test-token" not in message


def test_already_sent_private_reply_subcode():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "Already replied", "code": 100, "error_subcode": 2534014}},
        )

    client, _, _ = make_client(handler)

    async def go():
        async with client:
            await client.send_private_reply("c1", "hello")

    with pytest.raises(InstagramError) as excinfo:
        run(go())
    assert excinfo.value.is_already_sent is True


def test_network_error_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client, calls, _ = make_client(handler, retries=0)

    async def go():
        async with client:
            await client.reply_to_comment("c", "hi")

    with pytest.raises(InstagramError) as excinfo:
        run(go())
    assert "Could not reach the Instagram API" in str(excinfo.value)
    assert len(calls) == 1
