"""Test doubles for the Instagram Graph API client."""

from __future__ import annotations

from typing import Any

from instagram import InstagramError


class FakeInstagramClient:
    """Async context manager mimicking ``InstagramClient``.

    Configure behaviour per test by setting attributes or passing callables.
    """

    instances: list["FakeInstagramClient"] = []

    def __init__(
        self,
        *args,
        reply_result: dict[str, Any] | None = None,
        dm_result: dict[str, Any] | None = None,
        private_error: Exception | None = None,
        reply_error: Exception | None = None,
        account_info: dict[str, Any] | None = None,
        post_details: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        self.args = args
        self.kwargs = kwargs
        self.reply_result = reply_result if reply_result is not None else {"id": "reply_123"}
        self.dm_result = dm_result if dm_result is not None else {
            "message_id": "mid_123",
            "recipient_id": "987654321",
        }
        self.private_error = private_error
        self.reply_error = reply_error
        self.account_info = account_info or {
            "id": "17841400000000000",
            "username": "fawziko.studio",
            "name": "Fawziko Studio",
            "profile_picture_url": "",
            "followers_count": 18400,
        }
        self.post_details = post_details or {
            "id": "17895695668004550",
            "caption": "A reel about pricing",
            "thumbnail_url": "https://cdn.example.test/thumb.jpg",
            "media_url": "",
            "permalink": "https://www.instagram.com/p/abc/",
            "media_type": "VIDEO",
            "media_product_type": "REELS",
            "timestamp": "2026-10-01T12:00:00+0000",
            "username": "fawziko.studio",
            "like_count": 100,
            "comments_count": 4,
        }
        self.calls: list[tuple[str, tuple, dict]] = []
        FakeInstagramClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def reply_to_comment(self, comment_id: str, message: str):
        self.calls.append(("reply_to_comment", (comment_id, message), {}))
        if self.reply_error:
            raise self.reply_error
        return self.reply_result

    async def send_private_reply(self, comment_id: str, message: str):
        self.calls.append(("send_private_reply", (comment_id, message), {}))
        if self.private_error:
            raise self.private_error
        return self.dm_result

    async def send_dm(self, instagram_user_id: str, message: str):
        self.calls.append(("send_dm", (instagram_user_id, message), {}))
        return self.dm_result

    async def get_account_info(self):
        self.calls.append(("get_account_info", (), {}))
        return self.account_info

    async def get_post_details(self, post_id: str):
        self.calls.append(("get_post_details", (post_id,), {}))
        return self.post_details

    async def subscribe_webhooks(self, fields: str = "comments,messages"):
        self.calls.append(("subscribe_webhooks", (fields,), {}))
        return fields.split(",")

    async def get_subscribed_apps(self):
        return [{"subscribed_fields": ["comments", "messages"]}]


def already_sent_error() -> InstagramError:
    return InstagramError(
        "This comment already received a private reply.",
        status_code=400,
        code=100,
        subcode=2534014,
    )
