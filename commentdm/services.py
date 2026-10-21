"""Domain logic: campaign matching, comment processing, settings and stats."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from instagram import (
    InstagramClient,
    InstagramConfigError,
    InstagramError,
    refresh_long_lived_token,
)
from keywords import best_keyword, split_keywords
from models import Campaign, Config, ProcessedComment
from utils import iso, mask_secret, truncate, utcnow

logger = logging.getLogger(__name__)

DELIVERED_STATES = ("sent", "already_sent")


class NoKeywordMatch(ValueError):
    """The sample comment does not contain any keyword of the campaign."""


@dataclass(frozen=True)
class Credentials:
    access_token: str
    instagram_business_account_id: str
    page_id: str
    token_source: str

    @property
    def account_id(self) -> str:
        """Alias used by routes when filtering incoming webhook entries."""
        return self.instagram_business_account_id


# --------------------------------------------------------------------- config
def get_config(db: Session) -> Config | None:
    return db.get(Config, 1)


def get_or_create_config(db: Session) -> Config:
    config = db.get(Config, 1)
    if config is None:
        config = Config(id=1)
        db.add(config)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            config = db.get(Config, 1)
        else:
            db.refresh(config)
    return config


def effective_credentials(db: Session) -> Credentials:
    """Database values win over environment values."""
    settings = get_settings()
    config = get_config(db)

    db_token = (config.access_token or "").strip() if config else ""
    env_token = settings.instagram_access_token.strip()
    token = db_token or env_token

    db_ig_id = (config.instagram_business_account_id or "").strip() if config else ""
    ig_id = db_ig_id or settings.instagram_business_account_id.strip()

    page_id = (config.page_id or "").strip() if config else ""

    if db_token:
        source = "database"
    elif env_token:
        source = "environment"
    else:
        source = "none"

    return Credentials(
        access_token=token,
        instagram_business_account_id=ig_id,
        page_id=page_id,
        token_source=source,
    )


def serialize_config(db: Session) -> dict[str, Any]:
    """Safe settings payload — never includes the raw token or app secret."""
    settings = get_settings()
    config = get_config(db)
    creds = effective_credentials(db)
    return {
        "page_id": creds.page_id or None,
        "instagram_business_account_id": creds.instagram_business_account_id or None,
        "has_instagram_account_id": bool(creds.instagram_business_account_id),
        "instagram_username": config.instagram_username if config else None,
        "has_access_token": bool(creds.access_token),
        "access_token_masked": mask_secret(creds.access_token),
        "token_source": creds.token_source,
        "token_refresh_available": bool(
            settings.instagram_app_id
            and (settings.instagram_app_secret or settings.facebook_app_secret)
        ),
        "updated_at": iso(config.updated_at) if config else None,
        "webhook": {
            "app_secret_configured": bool(settings.facebook_app_secret),
            "verify_token_configured": bool(settings.webhook_verify_token),
            "signature_required": not settings.allow_unsigned_webhooks,
            "unsigned_allowed": settings.allow_unsigned_webhooks,
            "public_base_url": settings.public_base_url or None,
        },
        "dashboard_auth_enabled": settings.dashboard_auth_enabled,
    }


def save_config(
    db: Session,
    *,
    access_token: str | None = None,
    page_id: str | None = None,
    instagram_business_account_id: str | None = None,
    clear_access_token: bool = False,
) -> Config:
    config = get_or_create_config(db)
    if clear_access_token:
        config.access_token = None
    elif access_token:
        if access_token != config.access_token:
            # The cached username belongs to the previous token.
            config.instagram_username = None
        config.access_token = access_token

    if page_id is not None:
        config.page_id = page_id or None
    if instagram_business_account_id is not None:
        config.instagram_business_account_id = instagram_business_account_id or None

    config.updated_at = utcnow()
    db.commit()
    db.refresh(config)
    return config


async def refresh_and_save_token(db: Session) -> dict[str, Any]:
    settings = get_settings()
    creds = effective_credentials(db)
    if not creds.access_token:
        raise InstagramConfigError("No access token is configured yet.")
    secret = settings.instagram_app_secret or settings.facebook_app_secret
    if not settings.instagram_app_id or not secret:
        raise InstagramConfigError(
            "Set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET (or FACEBOOK_APP_SECRET) "
            "to enable token refresh."
        )
    result = await refresh_long_lived_token(
        creds.access_token,
        settings.instagram_app_id,
        secret,
        base_url=settings.graph_api_base_url,
        api_version=settings.graph_api_version,
        timeout=settings.graph_timeout_seconds,
    )
    config = get_or_create_config(db)
    config.access_token = result["access_token"]
    config.instagram_username = None
    config.updated_at = utcnow()
    db.commit()
    logger.info("Refreshed the long-lived Instagram token and saved it to the database.")
    return result


# ------------------------------------------------------------------- matching
def find_matching_campaign(
    db: Session, post_id: str, comment_text: str
) -> tuple[Campaign | None, str | None]:
    """Return the best active campaign + keyword for a comment.

    The longest keyword wins; ties prefer the most recently created campaign.
    """
    post_id = str(post_id or "").strip()
    if not post_id or not comment_text:
        return None, None
    campaigns = db.scalars(
        select(Campaign)
        .where(Campaign.is_active.is_(True), Campaign.post_id == post_id)
        .order_by(Campaign.id.desc())
    ).all()

    best: tuple[int, int, Campaign, str] | None = None
    for campaign in campaigns:
        keyword = best_keyword(split_keywords(campaign.keywords), comment_text)
        if not keyword:
            continue
        # Longer keywords are more specific. On a tie the newest campaign wins;
        # the query is ordered newest first, so only a strict improvement
        # replaces the current best.
        score = (len(keyword), campaign.id)
        if best is None or score > (best[0], best[1]):
            best = (len(keyword), campaign.id, campaign, keyword)
    if best is None:
        return None, None
    return best[2], best[3]


def match_explanation(db: Session, post_id: str, comment_text: str) -> dict[str, Any]:
    campaign, keyword = find_matching_campaign(db, post_id, comment_text)
    return {
        "matched": campaign is not None,
        "campaign": campaign,
        "keyword": keyword,
    }


# ---------------------------------------------------------------- processing
def _new_record(
    *,
    comment_id: str,
    campaign: Campaign,
    post_id: str,
    text: str,
    commenter_id: str | None,
    commenter_username: str | None,
    keyword: str,
    status: str = "processing",
) -> ProcessedComment:
    return ProcessedComment(
        comment_id=comment_id,
        campaign_id=campaign.id,
        post_id=str(post_id or campaign.post_id),
        commenter_id=commenter_id,
        commenter_username=truncate(commenter_username or "", 120) or None,
        comment_text=truncate(text, 2000),
        matched_keyword=keyword,
        status=status,
        comment_reply_status="pending",
        dm_status="pending",
    )


def build_client(db: Session) -> InstagramClient:
    """Create a Graph client from the current credentials.

    Kept as a module-level function so tests can substitute a fake transport.
    """
    settings = get_settings()
    creds = effective_credentials(db)
    if not creds.access_token:
        raise InstagramConfigError(
            "No Instagram access token is configured. Open Settings and save a "
            "long-lived access token, or set INSTAGRAM_ACCESS_TOKEN."
        )
    return InstagramClient(
        creds.access_token,
        account_id=creds.instagram_business_account_id or None,
        base_url=settings.graph_api_base_url,
        api_version=settings.graph_api_version,
        timeout=settings.graph_timeout_seconds,
    )


async def _deliver(
    db: Session,
    record: ProcessedComment,
    campaign: Campaign,
    *,
    comment_id: str,
    text: str,
    commenter_id: str | None,
) -> None:
    creds = effective_credentials(db)
    errors: list[str] = []
    reply_status = "failed"
    dm_status = "failed"
    reply_comment_id: str | None = None
    dm_message_id: str | None = None

    if not creds.access_token:
        errors.append(
            "No Instagram access token is configured (Settings → Instagram credentials)."
        )
    else:
        try:
            client = build_client(db)
        except InstagramConfigError as exc:
            errors.append(str(exc))
            client = None

        if client is not None:
            async with client:
                # 1. Public reply under the comment.
                try:
                    result = await client.reply_to_comment(comment_id, campaign.comment_reply)
                    reply_status = "sent"
                    reply_comment_id = result.get("id") or None
                except InstagramError as exc:
                    reply_status = "failed"
                    errors.append(f"Public reply failed: {exc.public_message()}")
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Unexpected error while replying to comment %s", comment_id)
                    errors.append("Public reply failed: unexpected error (see server logs).")

                # 2. Private reply (DM) to the commenter.
                if not creds.instagram_business_account_id:
                    errors.append(
                        "DM not sent: add your Instagram Business Account ID in Settings."
                    )
                else:
                    try:
                        result = await client.send_private_reply(comment_id, campaign.dm_message)
                        dm_status = "sent"
                        dm_message_id = result.get("message_id")
                    except InstagramError as exc:
                        if exc.is_already_sent:
                            dm_status = "already_sent"
                            errors.append(
                                "Instagram reports that a private reply was already sent "
                                "for this comment."
                            )
                        else:
                            dm_note = exc.public_message()
                            if commenter_id and not exc.is_rate_limit:
                                # The private reply can fail when the comment surface is
                                # unsupported. A normal DM only succeeds if an existing
                                # conversation is open, but it is worth one attempt.
                                try:
                                    result = await client.send_dm(
                                        commenter_id, campaign.dm_message
                                    )
                                    dm_status = "sent"
                                    dm_message_id = result.get("message_id")
                                    errors.append(
                                        f"Private reply failed ({dm_note}); message "
                                        "delivered via the existing DM conversation instead."
                                    )
                                except InstagramError as fallback_exc:
                                    dm_status = "failed"
                                    errors.append(
                                        f"DM failed: {dm_note} Fallback DM also failed: "
                                        f"{fallback_exc.public_message()}"
                                    )
                            else:
                                dm_status = "failed"
                                errors.append(f"DM failed: {dm_note}")
                    except Exception:  # pragma: no cover - defensive
                        logger.exception("Unexpected error while DMing comment %s", comment_id)
                        errors.append("DM failed: unexpected error (see server logs).")

    record.comment_reply_status = reply_status
    record.dm_status = dm_status
    record.reply_comment_id = reply_comment_id
    record.dm_message_id = dm_message_id
    record.error_detail = truncate(" ".join(errors), 1500) or None
    if reply_status == "sent" and dm_status in DELIVERED_STATES:
        record.status = "success"
    elif reply_status == "sent" or dm_status in DELIVERED_STATES:
        record.status = "partial"
    else:
        record.status = "failed"
    record.processed_at = utcnow()


async def process_comment(
    db: Session,
    *,
    comment_id: str,
    text: str,
    post_id: str,
    commenter_id: str | None = None,
    commenter_username: str | None = None,
    dry_run: bool = False,
) -> ProcessedComment | None:
    """Match and act on one comment.

    Returns the activity record, or ``None`` when the comment is a duplicate or
    does not match any active campaign. The dedupe row is committed *before*
    any Instagram call, so Meta's retries can never double-send.
    """
    comment_id = str(comment_id or "").strip()
    if not comment_id:
        return None

    campaign, keyword = find_matching_campaign(db, post_id, text)
    if campaign is None or keyword is None:
        return None

    record = _new_record(
        comment_id=comment_id,
        campaign=campaign,
        post_id=post_id,
        text=text,
        commenter_id=commenter_id,
        commenter_username=commenter_username,
        keyword=keyword,
        status="processing",
    )
    campaign_id = campaign.id
    record_id = None

    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("Duplicate comment %s ignored (dedupe ledger).", comment_id)
        return None
    record_id = record.id

    if dry_run:
        record.status = "simulated"
        record.comment_reply_status = "simulated"
        record.dm_status = "simulated"
        record.error_detail = "Dry run — no Instagram API request was made."
        record.processed_at = utcnow()
        db.commit()
        return record

    try:
        await _deliver(
            db,
            record,
            campaign,
            comment_id=comment_id,
            text=text,
            commenter_id=commenter_id,
        )
        campaign = db.get(Campaign, campaign_id) or campaign
        campaign.times_triggered = (campaign.times_triggered or 0) + 1
        campaign.last_triggered_at = record.processed_at
        db.commit()
    except Exception:  # pragma: no cover - defensive, keep the ledger intact
        logger.exception("Failed to finish processing comment %s", comment_id)
        db.rollback()
        fresh = db.get(ProcessedComment, record_id) if record_id else None
        if fresh is not None and fresh.status == "processing":
            fresh.status = "failed"
            fresh.error_detail = "Processing failed unexpectedly. See server logs."
            fresh.processed_at = utcnow()
            db.commit()
        return fresh

    return record


def simulate_campaign(
    db: Session,
    campaign: Campaign,
    comment_text: str,
    commenter_username: str | None = None,
) -> ProcessedComment:
    """Record a dry run without touching Instagram or the campaign counters."""
    keyword = best_keyword(split_keywords(campaign.keywords), comment_text)
    if not keyword:
        raise NoKeywordMatch(
            "That comment doesn't contain any of this campaign's keywords "
            f"({campaign.keywords})."
        )
    record = _new_record(
        comment_id=f"simulation-{uuid.uuid4().hex}",
        campaign=campaign,
        post_id=campaign.post_id,
        text=comment_text,
        commenter_id=None,
        commenter_username=commenter_username or "test_commenter",
        keyword=keyword,
        status="simulated",
    )
    record.comment_reply_status = "simulated"
    record.dm_status = "simulated"
    record.error_detail = "Dry run — no Instagram API request was made."
    record.processed_at = utcnow()
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# --------------------------------------------------------------- serializers
def serialize_campaign(campaign: Campaign) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "name": campaign.name,
        # The edit form shows raw_name so an auto-derived caption name can be
        # replaced without losing the original label.
        "raw_name": campaign.name,
        "post_id": campaign.post_id,
        "keywords": campaign.keywords,
        "keyword_list": split_keywords(campaign.keywords),
        "comment_reply": campaign.comment_reply,
        "dm_message": campaign.dm_message,
        "is_active": bool(campaign.is_active),
        "post_thumbnail_url": campaign.post_thumbnail_url,
        "post_caption": campaign.post_caption,
        "post_permalink": campaign.post_permalink,
        "times_triggered": campaign.times_triggered or 0,
        "last_triggered_at": iso(campaign.last_triggered_at),
        "created_at": iso(campaign.created_at),
        "updated_at": iso(campaign.updated_at),
    }


def serialize_activity(record: ProcessedComment) -> dict[str, Any]:
    return {
        "id": record.id,
        "comment_id": record.comment_id,
        "campaign_id": record.campaign_id,
        "campaign_name": record.campaign.name if record.campaign else "Deleted campaign",
        "post_id": record.post_id,
        "commenter_username": record.commenter_username,
        "comment_text": record.comment_text,
        "matched_keyword": record.matched_keyword,
        "status": record.status,
        "comment_reply_status": record.comment_reply_status,
        "dm_status": record.dm_status,
        "error_detail": record.error_detail,
        "created_at": iso(record.created_at),
        "processed_at": iso(record.processed_at),
    }


def compute_stats(db: Session) -> dict[str, Any]:
    def scalar(stmt: Any) -> int:
        return int(db.scalar(stmt) or 0)

    campaigns_total = scalar(select(func.count(Campaign.id)))
    campaigns_active = scalar(
        select(func.count(Campaign.id)).where(Campaign.is_active.is_(True))
    )

    real = ProcessedComment.status != "simulated"
    comments_matched = scalar(select(func.count(ProcessedComment.id)).where(real))
    simulations = scalar(
        select(func.count(ProcessedComment.id)).where(
            ProcessedComment.status == "simulated"
        )
    )
    replies_sent = scalar(
        select(func.count(ProcessedComment.id)).where(
            ProcessedComment.status != "simulated",
            ProcessedComment.comment_reply_status == "sent",
        )
    )
    dms_sent = scalar(
        select(func.count(ProcessedComment.id)).where(
            ProcessedComment.status != "simulated",
            ProcessedComment.dm_status.in_(DELIVERED_STATES),
        )
    )
    successful = scalar(
        select(func.count(ProcessedComment.id)).where(
            ProcessedComment.status != "simulated",
            ProcessedComment.comment_reply_status == "sent",
            ProcessedComment.dm_status.in_(DELIVERED_STATES),
        )
    )
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    processed_today = scalar(
        select(func.count(ProcessedComment.id)).where(
            ProcessedComment.status != "simulated",
            ProcessedComment.created_at >= start_of_day,
        )
    )
    last_activity = db.scalar(select(func.max(ProcessedComment.created_at)).where(real))

    return {
        "campaigns_total": campaigns_total,
        "campaigns_active": campaigns_active,
        "campaigns_paused": max(0, campaigns_total - campaigns_active),
        "comments_matched": comments_matched,
        "matches": comments_matched,
        "simulations": simulations,
        "replies_sent": replies_sent,
        "dms_sent": dms_sent,
        "success_rate": round((successful / comments_matched) * 100) if comments_matched else 0,
        "processed_today": processed_today,
        "today": processed_today,
        "last_activity_at": iso(last_activity),
    }


# ----------------------------------------------------------------------- demo
def seed_demo_data(db: Session) -> dict[str, int]:
    """Populate two sample campaigns and three simulated activity rows.

    Only allowed on an empty account so a click can never mix fake data into a
    working automation. Everything is clearly labelled "Sample — " and all
    activity is recorded as simulated (no Graph API call).
    """
    existing = int(db.scalar(select(func.count(Campaign.id))) or 0)
    if existing:
        raise ValueError(
            "Sample data can only be loaded when there are no campaigns yet."
        )

    now = utcnow()
    campaigns = [
        Campaign(
            name="Sample — Pricing reel",
            post_id="17900000000000001",
            keywords="price, pricing, how much, cost",
            comment_reply="Just sent the full price list to your DMs 💌",
            dm_message=(
                "Hey! Here's the price list you asked for. Reply here if you'd "
                "like help choosing a package."
            ),
            is_active=True,
            post_caption=(
                "Behind the scenes of our newest launch — swipe through for the "
                "full breakdown. Comment PRICE and we'll DM you the details."
            ),
            post_permalink="https://www.instagram.com/",
        ),
        Campaign(
            name="Sample — Free guide",
            post_id="17900000000000002",
            keywords="guide, template, freebie",
            comment_reply="Sent! Check your inbox 📩",
            dm_message=(
                "Thanks for commenting! Here's the free template: "
                "https://example.com/template — enjoy!"
            ),
            is_active=False,
            post_caption=(
                "The exact template we use for every launch. Comment GUIDE and "
                "we'll send it over."
            ),
            post_permalink="https://www.instagram.com/",
        ),
    ]
    db.add_all(campaigns)
    db.commit()
    for campaign in campaigns:
        db.refresh(campaign)

    samples = [
        (
            campaigns[0],
            "demo-comment-1",
            "price please!",
            "price",
            "lina.creates",
            "987654321",
            4,
        ),
        (
            campaigns[0],
            "demo-comment-2",
            "how much is the launch package?",
            "how much",
            "omar.makes",
            "987654322",
            26,
        ),
        (
            campaigns[1],
            "demo-comment-3",
            "GUIDE 🙏",
            "guide",
            "studio.noor",
            "987654323",
            58,
        ),
    ]
    for campaign, comment_id, text, keyword, username, author_id, minutes in samples:
        when = now - timedelta(minutes=minutes)
        db.add(
            ProcessedComment(
                comment_id=comment_id,
                campaign_id=campaign.id,
                post_id=campaign.post_id,
                commenter_id=author_id,
                commenter_username=username,
                comment_text=text,
                matched_keyword=keyword,
                status="simulated",
                comment_reply_status="simulated",
                dm_status="simulated",
                error_detail="Sample activity — no Instagram request was made.",
                created_at=when,
                processed_at=when,
            )
        )
    db.commit()
    return {"campaigns": len(campaigns), "activity": len(samples)}


# ------------------------------------------------------------------ webhooks
def parse_comment_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract actionable comment events from a Meta webhook payload.

    Skips replies (they would double-DM), the account's own comments and
    entries without a media ID.
    """
    events: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return events
    if payload.get("object") not in (None, "instagram"):
        return events

    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        account_id = str(entry.get("id") or "")
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or change.get("field") != "comments":
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            comment_id = value.get("id")
            if not comment_id:
                continue
            author = value.get("from") or {}
            if not isinstance(author, dict):
                author = {}
            author_id = str(author.get("id") or "") or None
            if value.get("parent_id"):
                logger.debug("Skipping reply-to-comment %s", comment_id)
                continue
            if account_id and author_id and author_id == account_id:
                logger.debug("Skipping self-comment %s", comment_id)
                continue
            media = value.get("media") or {}
            media_id = media.get("id") if isinstance(media, dict) else None
            post_id = str(media_id or value.get("media_id") or "").strip()
            events.append(
                {
                    "comment_id": str(comment_id),
                    "text": value.get("text") or "",
                    "post_id": post_id,
                    "commenter_id": author_id,
                    "commenter_username": author.get("username")
                    or value.get("username"),
                    "account_id": account_id,
                }
            )
    return events
