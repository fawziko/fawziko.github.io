"""Server-rendered dashboard pages (Jinja2, no build step)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

import services
from config import APP_TAGLINE, BASE_DIR, get_settings
from database import engine, get_db
from keywords import split_keywords
from models import Campaign, ProcessedComment
from security import require_dashboard_auth
from utils import format_dt, format_relative

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["dt"] = format_dt
templates.env.filters["relative"] = format_relative
templates.env.filters["num"] = lambda value: f"{int(value or 0):,}"
templates.env.globals["split_keywords"] = split_keywords

router = APIRouter(dependencies=[Depends(require_dashboard_auth)], include_in_schema=False)

FLASH_MESSAGES: dict[str, dict[str, str]] = {
    "settings_saved": {
        "type": "success",
        "title": "Settings saved",
        "message": "Credentials are stored on the server. Run a connection test to confirm them.",
    },
    "campaign_saved": {
        "type": "success",
        "title": "Campaign saved",
        "message": "Your automation is live as soon as the campaign is active.",
    },
    "campaign_deleted": {
        "type": "success",
        "title": "Campaign deleted",
        "message": "The campaign was removed. Its activity history is kept.",
    },
    "demo_loaded": {
        "type": "success",
        "title": "Sample data loaded",
        "message": "Two sample campaigns and simulated activity are ready to explore.",
    },
    "activity_cleared": {
        "type": "success",
        "title": "Activity cleared",
        "message": "The processed-comment ledger was reset, so comment IDs can fire again.",
    },
    "token_refreshed": {
        "type": "success",
        "title": "Token refreshed",
        "message": "A fresh long-lived access token has been saved.",
    },
}


def _flash(request: Request) -> dict[str, str] | None:
    key = request.query_params.get("flash")
    return FLASH_MESSAGES.get(key or "")


def _base_context(request: Request, db: Session, active: str) -> dict[str, Any]:
    settings = get_settings()
    config = services.get_config(db)
    creds = services.effective_credentials(db)
    public_base = settings.public_base_url
    return {
        "request": request,
        "active": active,
        "app_name": settings.app_name,
        "tagline": APP_TAGLINE,
        "version": settings.version,
        "graph_version": settings.graph_api_version,
        "connected": bool(creds.access_token and creds.account_id),
        "has_token": bool(creds.access_token),
        "account_username": (config.instagram_username if config else None),
        "active_campaign_count": int(
            db.scalar(
                select(func.count(Campaign.id)).where(Campaign.is_active.is_(True))
            )
            or 0
        ),
        "flash": _flash(request),
        "public_base_url": public_base,
        "webhook_url": f"{public_base}/webhook/instagram" if public_base else "",
        "demo_available": int(db.scalar(select(func.count(Campaign.id))) or 0) == 0,
    }


@router.get("/", response_class=HTMLResponse)
def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@router.get("/dashboard", response_class=HTMLResponse)
def campaigns_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    campaigns = db.scalars(
        select(Campaign).order_by(Campaign.is_active.desc(), Campaign.created_at.desc())
    ).all()
    recent = db.scalars(
        select(ProcessedComment)
        .options(joinedload(ProcessedComment.campaign))
        .order_by(ProcessedComment.created_at.desc())
        .limit(6)
    ).all()
    context = {
        **_base_context(request, db, "campaigns"),
        "campaigns": campaigns,
        "stats": services.compute_stats(db),
        "recent": recent,
    }
    return templates.TemplateResponse(request, "campaigns.html", context)


@router.get("/dashboard/campaigns", response_class=HTMLResponse)
def campaigns_alias() -> RedirectResponse:
    return RedirectResponse(url="/dashboard", status_code=307)


@router.get("/dashboard/activity", response_class=HTMLResponse)
def activity_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    records = db.scalars(
        select(ProcessedComment)
        .options(joinedload(ProcessedComment.campaign))
        .order_by(ProcessedComment.created_at.desc())
        .limit(300)
    ).all()
    campaigns = db.scalars(select(Campaign).order_by(Campaign.name.asc())).all()
    context = {
        **_base_context(request, db, "activity"),
        "records": records,
        "campaigns": campaigns,
        "stats": services.compute_stats(db),
    }
    return templates.TemplateResponse(request, "activity.html", context)


@router.get("/dashboard/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    settings = get_settings()
    state = services.serialize_config(db)
    config = services.get_config(db)

    env_items = [
        {
            "name": "INSTAGRAM_ACCESS_TOKEN",
            "label": "Instagram access token",
            "description": "Long-lived User token. Can also be saved in the form on this page.",
            "configured": state["has_access_token"],
            "required": True,
            "source": state["token_source"],
        },
        {
            "name": "INSTAGRAM_BUSINESS_ACCOUNT_ID",
            "label": "Instagram Business Account ID",
            "description": "The IG professional account ID used for DM delivery.",
            "configured": state["has_instagram_account_id"],
            "required": True,
            "source": "database" if config and config.instagram_business_account_id else (
                "environment" if settings.instagram_business_account_id else "none"
            ),
        },
        {
            "name": "FACEBOOK_APP_SECRET",
            "label": "Facebook App secret",
            "description": "Validates X-Hub-Signature-256 on every webhook.",
            "configured": bool(settings.facebook_app_secret),
            "required": True,
            "source": "environment",
        },
        {
            "name": "WEBHOOK_VERIFY_TOKEN",
            "label": "Webhook verify token",
            "description": "The string you enter in Meta's webhook configuration.",
            "configured": bool(settings.webhook_verify_token),
            "required": True,
            "source": "environment",
        },
        {
            "name": "INSTAGRAM_APP_ID + APP_SECRET",
            "label": "Token refresh (optional)",
            "description": "Enables the one-click 60-day token refresh below.",
            "configured": bool(settings.instagram_app_id)
            and bool(settings.instagram_app_secret or settings.facebook_app_secret),
            "required": False,
            "source": "environment",
        },
        {
            "name": "PUBLIC_BASE_URL",
            "label": "Public base URL",
            "description": "Used to display the exact webhook callback URL.",
            "configured": bool(settings.public_base_url),
            "required": False,
            "source": "environment",
        },
        {
            "name": "DASHBOARD_USERNAME + PASSWORD",
            "label": "Dashboard login",
            "description": "HTTP Basic protection for the dashboard and API.",
            "configured": settings.dashboard_auth_enabled,
            "required": False,
            "source": "environment",
        },
    ]

    context = {
        **_base_context(request, db, "settings"),
        "state": state,
        "config": config,
        "env_items": env_items,
        "signature_required": settings.webhook_signature_required,
        "app_secret_configured": bool(settings.facebook_app_secret),
        "verify_token_configured": bool(settings.webhook_verify_token),
        "dashboard_auth_enabled": settings.dashboard_auth_enabled,
        "instagram_app_configured": bool(settings.instagram_app_id)
        and bool(settings.instagram_app_secret or settings.facebook_app_secret),
        "database_backend": {
            "sqlite": "SQLite",
            "postgresql": "PostgreSQL",
        }.get(engine.dialect.name, engine.dialect.name.title()),
        "graph_api_version": settings.graph_api_version,
    }
    return templates.TemplateResponse(request, "settings.html", context)
