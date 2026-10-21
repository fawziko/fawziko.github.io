"""REST API used by the dashboard (all endpoints sit behind Basic auth if enabled)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

import services
from config import get_settings
from database import get_db
from instagram import InstagramConfigError, InstagramError, refresh_long_lived_token
from models import Campaign, ProcessedComment
from security import require_dashboard_auth
from schemas import (
    CampaignPayload,
    ConfigPayload,
    PostPreviewPayload,
    SimulatePayload,
)
from utils import truncate

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api",
    tags=["api"],
    dependencies=[Depends(require_dashboard_auth)],
)


def _campaign_or_404(db: Session, campaign_id: int) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


async def _enrich_campaign(db: Session, campaign: Campaign, *, force: bool = False) -> str | None:
    """Fetch caption/thumbnail from the Graph API and cache it on the campaign.

    Never fails the save: returns a warning string instead.
    """
    if not force and campaign.post_thumbnail_url:
        return None
    try:
        client = services.build_client(db)
    except InstagramConfigError:
        return None  # Credentials not added yet; the campaign is still valid.
    try:
        async with client:
            details = await client.get_post_details(campaign.post_id)
    except InstagramError as exc:
        logger.info("Post preview failed for %s: %s", campaign.post_id, exc.public_message())
        return exc.public_message()
    except Exception:  # pragma: no cover - defensive
        logger.exception("Unexpected preview failure for post %s", campaign.post_id)
        return "Could not load the post preview."

    campaign.post_thumbnail_url = details.get("thumbnail_url") or None
    campaign.post_caption = details.get("caption") or None
    campaign.post_permalink = details.get("permalink") or None
    if not (campaign.name or "").strip() and details.get("caption"):
        campaign.name = truncate(details["caption"], 60)
    return None


# --------------------------------------------------------------------------- config
@router.get("/config")
def read_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    return services.serialize_config(db)


@router.put("/config")
def save_config(payload: ConfigPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    config = services.get_or_create_config(db)
    supplied = payload.model_fields_set

    if payload.clear_access_token:
        config.access_token = None
        config.instagram_username = None
    elif payload.access_token:
        if payload.access_token != config.access_token:
            config.instagram_username = None
        config.access_token = payload.access_token

    if "page_id" in supplied:
        config.page_id = (payload.page_id or "").strip() or None

    if "instagram_business_account_id" in supplied:
        new_account = (payload.instagram_business_account_id or "").strip() or None
        if new_account != config.instagram_business_account_id:
            config.instagram_username = None
        config.instagram_business_account_id = new_account

    db.commit()
    db.refresh(config)
    logger.info("Instagram credentials updated from the dashboard.")
    return services.serialize_config(db)


@router.post("/config/test")
async def test_connection(db: Session = Depends(get_db)) -> dict[str, Any]:
    creds = services.effective_credentials(db)
    if not creds.access_token:
        raise HTTPException(status_code=400, detail="Add an access token first.")
    if not creds.account_id:
        raise HTTPException(
            status_code=400, detail="Add your Instagram Business Account ID first."
        )
    try:
        client = services.build_client(db)
        async with client:
            info = await client.get_account_info()
    except InstagramConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InstagramError as exc:
        logger.warning("Connection test failed: %s", exc.public_message())
        raise HTTPException(status_code=400, detail=exc.public_message()) from exc

    config = services.get_or_create_config(db)
    config.instagram_username = info.get("username") or None
    db.commit()
    return {"ok": True, "account": info}


@router.post("/config/subscribe")
async def subscribe_webhooks(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        client = services.build_client(db)
    except InstagramConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not services.effective_credentials(db).account_id:
        raise HTTPException(
            status_code=400, detail="Add your Instagram Business Account ID first."
        )
    try:
        async with client:
            fields = await client.subscribe_webhooks()
    except InstagramError as exc:
        raise HTTPException(status_code=400, detail=exc.public_message()) from exc
    return {"ok": True, "subscribed_fields": fields}


@router.post("/config/refresh-token")
async def refresh_token(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    creds = services.effective_credentials(db)
    if not creds.access_token:
        raise HTTPException(status_code=400, detail="No access token to refresh.")
    if not settings.instagram_app_id or not (
        settings.instagram_app_secret or settings.facebook_app_secret
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Set INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET on the server to "
                "refresh tokens from the dashboard."
            ),
        )
    try:
        result = await refresh_long_lived_token(
            creds.access_token,
            settings.instagram_app_id,
            settings.instagram_app_secret or settings.facebook_app_secret,
            base_url=settings.graph_api_base_url,
            api_version=settings.graph_api_version,
            timeout=settings.graph_timeout_seconds,
        )
    except InstagramError as exc:
        raise HTTPException(status_code=400, detail=exc.public_message()) from exc

    token = result.get("access_token")
    if not token:
        raise HTTPException(status_code=400, detail="Facebook did not return a new token.")
    config = services.get_or_create_config(db)
    config.access_token = token
    db.commit()
    expires_in = result.get("expires_in")
    return {
        "ok": True,
        "expires_in": expires_in,
        "expires_in_days": round(expires_in / 86400) if expires_in else None,
        "config": services.serialize_config(db),
    }


# ------------------------------------------------------------------------ campaigns
@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)) -> dict[str, Any]:
    campaigns = db.scalars(
        select(Campaign).order_by(Campaign.is_active.desc(), Campaign.created_at.desc())
    ).all()
    return {"items": [services.serialize_campaign(c) for c in campaigns]}


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignPayload, db: Session = Depends(get_db)
) -> dict[str, Any]:
    campaign = Campaign(
        name=(payload.name or "").strip(),
        post_id=payload.post_id,
        keywords=payload.keywords,
        comment_reply=payload.comment_reply,
        dm_message=payload.dm_message,
        is_active=payload.is_active,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    warning = await _enrich_campaign(db, campaign, force=True)
    db.commit()
    db.refresh(campaign)

    result = services.serialize_campaign(campaign)
    if warning:
        result["preview_warning"] = warning
    return result


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return services.serialize_campaign(_campaign_or_404(db, campaign_id))


@router.put("/campaigns/{campaign_id}")
async def update_campaign(
    campaign_id: int, payload: CampaignPayload, db: Session = Depends(get_db)
) -> dict[str, Any]:
    campaign = _campaign_or_404(db, campaign_id)
    post_changed = campaign.post_id != payload.post_id

    campaign.name = (payload.name or "").strip()
    campaign.post_id = payload.post_id
    campaign.keywords = payload.keywords
    campaign.comment_reply = payload.comment_reply
    campaign.dm_message = payload.dm_message
    campaign.is_active = payload.is_active
    if post_changed:
        campaign.post_thumbnail_url = None
        campaign.post_caption = None
        campaign.post_permalink = None
    db.commit()

    warning = await _enrich_campaign(
        db, campaign, force=post_changed or not campaign.post_thumbnail_url
    )
    db.commit()
    db.refresh(campaign)

    result = services.serialize_campaign(campaign)
    if warning:
        result["preview_warning"] = warning
    return result


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)) -> Response:
    campaign = _campaign_or_404(db, campaign_id)
    db.delete(campaign)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/campaigns/{campaign_id}/toggle")
def toggle_campaign(campaign_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    campaign = _campaign_or_404(db, campaign_id)
    campaign.is_active = not campaign.is_active
    db.commit()
    db.refresh(campaign)
    return {
        "id": campaign.id,
        "is_active": campaign.is_active,
        "campaign": services.serialize_campaign(campaign),
        "stats": services.compute_stats(db),
    }


@router.post("/campaigns/{campaign_id}/simulate")
def simulate_campaign(
    campaign_id: int, payload: SimulatePayload, db: Session = Depends(get_db)
) -> dict[str, Any]:
    campaign = _campaign_or_404(db, campaign_id)
    try:
        record = services.simulate_campaign(
            db, campaign, payload.comment_text, payload.commenter_username
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "matched_keyword": record.matched_keyword,
        "comment_reply": campaign.comment_reply,
        "dm_message": campaign.dm_message,
        "activity": services.serialize_activity(record),
    }


# ---------------------------------------------------------------------- post preview
@router.post("/posts/preview")
async def preview_post(
    payload: PostPreviewPayload, db: Session = Depends(get_db)
) -> dict[str, Any]:
    try:
        client = services.build_client(db)
    except InstagramConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        async with client:
            details = await client.get_post_details(payload.post_id)
    except InstagramError as exc:
        # Fall back to previously cached metadata so edits still work offline.
        cached = db.scalars(
            select(Campaign)
            .where(
                Campaign.post_id == payload.post_id,
                Campaign.post_thumbnail_url.is_not(None),
            )
            .limit(1)
        ).first()
        if cached:
            return {
                "id": cached.post_id,
                "caption": cached.post_caption or "",
                "thumbnail_url": cached.post_thumbnail_url or "",
                "permalink": cached.post_permalink or "",
                "cached": True,
                "warning": exc.public_message(),
            }
        raise HTTPException(status_code=400, detail=exc.public_message()) from exc
    return {**details, "cached": False}


# -------------------------------------------------------------------------- activity
@router.get("/activity")
def list_activity(
    limit: int = Query(default=100, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
    campaign_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = (
        select(ProcessedComment)
        .options(joinedload(ProcessedComment.campaign))
        .order_by(ProcessedComment.created_at.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(ProcessedComment.status == status_filter)
    if campaign_id:
        stmt = stmt.where(ProcessedComment.campaign_id == campaign_id)
    records = db.scalars(stmt).all()
    return {"items": [services.serialize_activity(r) for r in records]}


@router.delete("/activity")
def clear_activity(db: Session = Depends(get_db)) -> dict[str, int]:
    """Clear the activity log. This also resets dedupe history (documented)."""
    result = db.execute(delete(ProcessedComment))
    db.commit()
    return {"deleted": int(result.rowcount or 0)}


@router.get("/stats")
def stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    return services.compute_stats(db)


# ----------------------------------------------------------------------------- demo
@router.post("/demo/seed")
def seed_demo(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        result = services.seed_demo_data(db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **result}
