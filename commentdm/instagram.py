"""Thin, reliable wrapper around Meta's official Instagram Graph API.

Only documented Graph API endpoints are used here:

* ``GET  /{ig-user-id}``                    – account details
* ``GET  /{media-id}``                      – post details (caption, thumbnail)
* ``POST /{comment-id}/replies``            – public reply to a comment
* ``POST /{ig-user-id}/messages``           – private reply (``recipient.comment_id``)
                                              or standard DM (``recipient.id``)
* ``POST /{ig-user-id}/subscribed_apps``    – subscribe the account to webhooks
* ``GET  /oauth/access_token``              – long-lived token refresh

No browser automation, scraping or unofficial endpoints are involved.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Graph API error codes that mean "you are going too fast, try again".
RATE_LIMIT_CODES = frozenset({4, 17, 32, 613})
# Subcode returned when a private reply was already sent for a comment.
PRIVATE_REPLY_ALREADY_SENT_SUBCODE = 2534014

POST_FIELDS = ",".join(
    [
        "id",
        "caption",
        "media_type",
        "media_product_type",
        "media_url",
        "thumbnail_url",
        "permalink",
        "timestamp",
        "username",
        "like_count",
        "comments_count",
    ]
)


class InstagramConfigError(RuntimeError):
    """Raised when the app does not hold enough credentials to call the API."""


class InstagramError(RuntimeError):
    """A user-presentable Graph API failure.

    ``str(exc)`` is safe to show in the dashboard: it never contains the access
    token. The original payload is kept in ``payload`` for debugging.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        fbtrace_id: str | None = None,
        user_message: str | None = None,
        is_rate_limit: bool = False,
        retryable: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.subcode = subcode
        self.fbtrace_id = fbtrace_id
        self.user_message = user_message
        self.is_rate_limit = is_rate_limit
        self.retryable = retryable
        self.payload = payload or {}

    @property
    def is_already_sent(self) -> bool:
        return self.subcode == PRIVATE_REPLY_ALREADY_SENT_SUBCODE

    def public_message(self) -> str:
        """A compact message suitable for the activity log."""
        parts = [self.message.strip()]
        if self.user_message and self.user_message.strip() not in parts[0]:
            parts.append(self.user_message.strip())
        details: list[str] = []
        if self.code is not None:
            details.append(f"code {self.code}")
        if self.subcode is not None:
            details.append(f"subcode {self.subcode}")
        if self.status_code is not None:
            details.append(f"HTTP {self.status_code}")
        if details:
            parts.append(f"({', '.join(details)})")
        return " ".join(parts)


def _error_from_response(response: httpx.Response, payload: dict[str, Any]) -> InstagramError:
    error = payload.get("error") if isinstance(payload, dict) else None
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    subcode = error.get("error_subcode")
    status = response.status_code
    is_rate = status == httpx.codes.TOO_MANY_REQUESTS or code in RATE_LIMIT_CODES
    message = error.get("message") or f"Instagram API returned HTTP {status}."
    return InstagramError(
        str(message),
        status_code=status,
        code=code if isinstance(code, int) else None,
        subcode=subcode if isinstance(subcode, int) else None,
        fbtrace_id=error.get("fbtrace_id"),
        user_message=error.get("error_user_msg"),
        is_rate_limit=is_rate,
        retryable=is_rate or status >= 500,
        payload=payload,
    )


def _decode(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    try:
        data = response.json()
    except ValueError:
        return {"raw": response.text[:500]}
    return data if isinstance(data, dict) else {"data": data}


class InstagramClient:
    """Async Graph API client with retry/backoff for throttling errors."""

    def __init__(
        self,
        access_token: str,
        *,
        account_id: str | None = None,
        base_url: str = "https://graph.facebook.com",
        api_version: str = "v23.0",
        timeout: float = 20.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if not access_token:
            raise InstagramConfigError(
                "No Instagram access token is configured. Add one under Settings."
            )
        self.access_token = access_token
        self.account_id = str(account_id) if account_id else None
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version if api_version.startswith("v") else f"v{api_version}"
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._transport = transport
        self._sleep = sleep or asyncio.sleep
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ http
    def _url(self, path: str) -> str:
        return f"{self.base_url}/{self.api_version}/{path.lstrip('/')}"

    async def __aenter__(self) -> InstagramClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                transport=self._transport,
                follow_redirects=False,
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("InstagramClient must be used as an async context manager.")
        return self._client

    def _backoff(self, attempt: int) -> float:
        # 1s, 2s, 4s … with a little jitter so retries from concurrent workers
        # do not line up.
        return min(30.0, float(2**attempt)) + random.uniform(0, 0.25)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"access_token": self.access_token}
        if params:
            query.update({k: v for k, v in params.items() if v is not None})

        last_error: InstagramError | None = None
        for attempt in range(self.max_retries + 1):
            started = time.perf_counter()
            try:
                response = await self._http.request(
                    method,
                    self._url(path),
                    params=query,
                    data=data,
                    json=json,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                last_error = InstagramError(
                    f"Could not reach the Instagram API ({exc.__class__.__name__}). "
                    "Check the server's outbound network access and try again."
                )
                if attempt < self.max_retries:
                    delay = self._backoff(attempt)
                    logger.warning(
                        "Graph %s /%s network error (%s), retrying in %.1fs",
                        method,
                        path,
                        exc.__class__.__name__,
                        delay,
                    )
                    await self._sleep(delay)
                    continue
                raise last_error from exc

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            payload = _decode(response)

            if response.status_code >= 400:
                error = _error_from_response(response, payload)
                logger.warning(
                    "Graph %s /%s -> %s in %sms | code=%s subcode=%s | %s",
                    method,
                    path,
                    response.status_code,
                    elapsed_ms,
                    error.code,
                    error.subcode,
                    error.message[:300],
                )
                last_error = error
                if error.retryable and attempt < self.max_retries:
                    delay = self._backoff(attempt)
                    logger.info(
                        "Graph rate limit/5xx, retrying %s /%s in %.1fs (attempt %s/%s)",
                        method,
                        path,
                        delay,
                        attempt + 1,
                        self.max_retries,
                    )
                    await self._sleep(delay)
                    continue
                raise error

            logger.info(
                "Graph %s /%s -> %s in %sms",
                method,
                path,
                response.status_code,
                elapsed_ms,
            )
            return payload

        # Defensive: the loop either returns or raises.
        raise last_error or InstagramError("Instagram API request failed.")

    # --------------------------------------------------------------- account
    async def get_account_info(self) -> dict[str, Any]:
        if not self.account_id:
            raise InstagramConfigError(
                "No Instagram Business Account ID is configured. Add it under Settings."
            )
        data = await self._request(
            "GET",
            self.account_id,
            params={
                "fields": "id,username,name,profile_picture_url,followers_count,media_count"
            },
        )
        return {
            "id": str(data.get("id") or self.account_id),
            "username": data.get("username"),
            "name": data.get("name"),
            "profile_picture_url": data.get("profile_picture_url"),
            "followers_count": data.get("followers_count"),
            "media_count": data.get("media_count"),
        }

    # ------------------------------------------------------------------ media
    async def get_post_details(self, post_id: str) -> dict[str, Any]:
        """Return caption + thumbnail for a media object."""
        data = await self._request("GET", str(post_id), params={"fields": POST_FIELDS})

        media_type = data.get("media_type")
        thumbnail = data.get("thumbnail_url") or ""
        if not thumbnail and media_type == "IMAGE":
            thumbnail = data.get("media_url") or ""
        if not thumbnail and media_type == "CAROUSEL_ALBUM":
            thumbnail = data.get("media_url") or ""

        return {
            "id": str(data.get("id") or post_id),
            "caption": data.get("caption") or "",
            "thumbnail_url": thumbnail,
            "permalink": data.get("permalink"),
            "media_type": media_type,
            "media_product_type": data.get("media_product_type"),
            "timestamp": data.get("timestamp"),
            "username": data.get("username"),
            "like_count": data.get("like_count"),
            "comments_count": data.get("comments_count"),
        }

    # --------------------------------------------------------------- comments
    async def reply_to_comment(self, comment_id: str, message: str) -> dict[str, Any]:
        """Publicly reply under a comment (``POST /{comment-id}/replies``)."""
        data = await self._request(
            "POST",
            f"{comment_id}/replies",
            data={"message": message},
        )
        return {"id": str(data.get("id") or "")}

    # --------------------------------------------------------------- messages
    async def send_private_reply(self, comment_id: str, message: str) -> dict[str, Any]:
        """Send the one allowed private reply for a comment.

        This is the sanctioned way to move a commenter into the inbox without
        them messaging the business first. Meta allows one private reply per
        comment within seven days.
        """
        if not self.account_id:
            raise InstagramConfigError(
                "No Instagram Business Account ID is configured. Add it under Settings."
            )
        data = await self._request(
            "POST",
            f"{self.account_id}/messages",
            json={
                "recipient": {"comment_id": str(comment_id)},
                "message": {"text": message},
            },
        )
        return {
            "message_id": data.get("message_id"),
            "recipient_id": data.get("recipient_id"),
        }

    async def send_dm(self, instagram_user_id: str, message: str) -> dict[str, Any]:
        """Send a standard DM to a user.

        Standard DMs only work when the user has an open conversation with the
        business (they messaged first, within the 24-hour window, or you hold an
        approved messaging tag). The automation prefers :meth:`send_private_reply`.
        """
        if not self.account_id:
            raise InstagramConfigError(
                "No Instagram Business Account ID is configured. Add it under Settings."
            )
        data = await self._request(
            "POST",
            f"{self.account_id}/messages",
            json={
                "recipient": {"id": str(instagram_user_id)},
                "message": {"text": message},
            },
        )
        return {
            "message_id": data.get("message_id"),
            "recipient_id": data.get("recipient_id"),
        }

    # -------------------------------------------------------------- webhooks
    async def subscribe_webhooks(self, fields: str = "comments,messages") -> list[str]:
        """Subscribe the Instagram account to comment webhooks.

        Returns the list of fields Meta reports as subscribed. The app-level
        callback URL still has to be configured in the Meta dashboard.
        """
        if not self.account_id:
            raise InstagramConfigError(
                "Add your Instagram Business Account ID before subscribing to webhooks."
            )
        await self._request(
            "POST",
            f"{self.account_id}/subscribed_apps",
            data={"subscribed_fields": fields},
        )
        requested = [field.strip() for field in fields.split(",") if field.strip()]
        try:
            subscribed = await self._request("GET", f"{self.account_id}/subscribed_apps")
        except InstagramError:
            # The subscription itself succeeded; do not fail the request just
            # because the read-back did.
            return requested
        apps = subscribed.get("data") or []
        found = sorted(
            {
                field
                for app in apps
                if isinstance(app, dict)
                for field in (app.get("subscribed_fields") or [])
            }
        )
        return found or requested

    # ----------------------------------------------------------- token refresh
    async def refresh_long_lived_token(self, app_id: str, app_secret: str) -> dict[str, Any]:
        """Exchange the current token for a fresh ~60-day token."""
        if not app_id or not app_secret:
            raise InstagramConfigError(
                "INSTAGRAM_APP_ID and an app secret are required to refresh the token."
            )
        response = await self._http.get(
            self._url("oauth/access_token"),
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": self.access_token,
            },
            headers={"Accept": "application/json"},
        )
        payload = _decode(response)
        if response.status_code >= 400:
            raise _error_from_response(response, payload)
        token = payload.get("access_token")
        if not token:
            raise InstagramError(
                "Meta did not return a refreshed token. Generate a new long-lived "
                "token in the Graph API Explorer."
            )
        return {
            "access_token": token,
            "token_type": payload.get("token_type"),
            "expires_in": payload.get("expires_in"),
        }


async def refresh_long_lived_token(
    current_token: str,
    app_id: str,
    app_secret: str,
    *,
    base_url: str = "https://graph.facebook.com",
    api_version: str = "v23.0",
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Module-level helper for CLI scripts and tests."""
    async with InstagramClient(
        current_token,
        base_url=base_url,
        api_version=api_version,
        timeout=timeout,
    ) as client:
        return await client.refresh_long_lived_token(app_id, app_secret)
