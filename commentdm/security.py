"""Authentication helpers for the two very different entry points:

* Meta webhooks are authenticated with ``X-Hub-Signature-256`` (HMAC-SHA256).
* The dashboard and JSON API use optional HTTP Basic authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config import get_settings

logger = logging.getLogger(__name__)

_basic = HTTPBasic(auto_error=False)


def compute_signature(secret: str, body: bytes) -> str:
    """Return the value Meta puts in ``X-Hub-Signature-256``."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """Validate a webhook payload signature in constant time (Meta order)."""
    if not secret or not signature:
        return False
    header = signature.strip()
    if not header.startswith("sha256="):
        return False
    received = header[len("sha256=") :].strip()
    expected = compute_signature(secret, body)[len("sha256=") :]
    try:
        return hmac.compare_digest(received, expected)
    except TypeError:  # pragma: no cover - non-ascii signature header
        return False


# Backwards-friendly alias: some call sites read better with the explicit name.
verify_webhook_signature = verify_signature


async def require_dashboard_auth(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> None:
    """Protect the dashboard/API when Basic auth is configured.

    When no credentials are configured the app stays open (handy for local
    development) and logs a warning at startup instead.
    """
    settings = get_settings()
    if not settings.dashboard_auth_enabled:
        return
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": 'Basic realm="CommentDM"'},
        )
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.dashboard_username.encode("utf-8"),
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.dashboard_password.encode("utf-8"),
    )
    if not (user_ok and pass_ok):
        logger.warning("Failed dashboard login for user %r", credentials.username[:80])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
            headers={"WWW-Authenticate": 'Basic realm="CommentDM"'},
        )
