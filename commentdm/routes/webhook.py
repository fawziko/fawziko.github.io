"""Meta webhook endpoints.

GET  /webhook/instagram  → verification challenge (hub.challenge)
POST /webhook/instagram  → signed comment events

Meta expects a fast 200. Processing (two Graph API calls) happens in a
background task *after* the response so retries are not triggered.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

import services
from config import get_settings
from database import SessionLocal, get_db
from security import verify_signature

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


@router.get("/webhook/instagram", response_class=PlainTextResponse)
async def verify_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
):
    """Answer Meta's verification request with the raw challenge."""
    settings = get_settings()
    expected = settings.webhook_verify_token

    if not expected:
        logger.error("Webhook verification attempted but WEBHOOK_VERIFY_TOKEN is not set.")
        raise HTTPException(
            status_code=503,
            detail="WEBHOOK_VERIFY_TOKEN is not configured on the server.",
        )

    if mode == "subscribe" and token and secrets.compare_digest(token, expected):
        logger.info("Meta webhook verification succeeded.")
        return PlainTextResponse(content=challenge or "")

    logger.warning("Rejected webhook verification attempt (mode=%r).", mode)
    raise HTTPException(status_code=403, detail="Webhook verification failed.")


async def _run_comment_event(event: dict[str, Any]) -> None:
    """Background worker: fresh DB session, never raises into the response."""
    with SessionLocal() as db:
        try:
            await services.process_comment(
                db,
                comment_id=event["comment_id"],
                text=event.get("text") or "",
                post_id=event.get("post_id") or "",
                commenter_id=event.get("commenter_id"),
                commenter_username=event.get("commenter_username"),
            )
        except Exception:
            db.rollback()
            logger.exception("Unhandled error processing comment %s", event.get("comment_id"))


@router.post("/webhook/instagram")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings = get_settings()
    raw_body = await request.body()

    # 1) Signature is mandatory unless a developer explicitly opted out.
    if settings.facebook_app_secret:
        signature = request.headers.get("x-hub-signature-256")
        if not verify_signature(settings.facebook_app_secret, raw_body, signature):
            client_ip = request.client.host if request.client else "unknown"
            logger.warning("Rejected unsigned/invalid webhook payload from %s.", client_ip)
            raise HTTPException(status_code=403, detail="Invalid X-Hub-Signature-256.")
    elif not settings.allow_unsigned_webhooks:
        logger.error(
            "Webhook rejected: FACEBOOK_APP_SECRET is not configured and unsigned "
            "webhooks are not allowed."
        )
        raise HTTPException(
            status_code=503,
            detail="Webhook signature verification is not configured.",
        )
    else:
        logger.warning(
            "Accepting an UNSIGNED webhook because ALLOW_UNSIGNED_WEBHOOKS=true. "
            "Never enable this in production."
        )

    # 2) Parse the payload.
    try:
        payload = json.loads(raw_body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON payload.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Unexpected webhook payload shape.")

    if payload.get("object") and payload.get("object") != "instagram":
        return {"status": "ignored", "queued": 0}

    events = services.parse_comment_events(payload)
    if not events:
        logger.debug("Webhook received with no actionable comment events.")
        return {"status": "received", "queued": 0}

    # 3) Only process events for the configured Instagram account (Meta sends
    #    events for every account connected to the app).
    creds = services.effective_credentials(db)
    queued = 0
    for event in events:
        if (
            creds.account_id
            and event.get("account_id")
            and event["account_id"] != creds.account_id
        ):
            logger.info(
                "Skipping comment %s from untracked Instagram account %s.",
                event["comment_id"],
                event["account_id"],
            )
            continue
        background_tasks.add_task(_run_comment_event, event)
        queued += 1

    return {"status": "received", "queued": queued}
