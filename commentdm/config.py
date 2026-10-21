"""Application configuration.

Every secret is read from the environment (or a local ``.env`` file) and is
never sent to the browser. The access token and Instagram account ID may also
be stored in the database from the Settings page; the database value wins over
the environment so a non-technical user can rotate credentials without a
redeploy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
# Load .env from the app directory regardless of the current working directory.
load_dotenv(BASE_DIR / ".env")

APP_NAME = "CommentDM"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Instagram comment-to-DM automation"


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _version(raw: str) -> str:
    value = (raw or "v23.0").strip()
    return value if value.startswith("v") else f"v{value}"


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    environment: str
    log_level: str

    # --- Instagram Graph API -------------------------------------------------
    instagram_access_token: str
    instagram_business_account_id: str
    instagram_app_id: str
    instagram_app_secret: str
    facebook_app_secret: str
    webhook_verify_token: str
    graph_api_version: str
    graph_api_base_url: str
    graph_timeout_seconds: float

    # --- Application ---------------------------------------------------------
    database_url: str
    public_base_url: str
    dashboard_username: str
    dashboard_password: str
    allow_unsigned_webhooks: bool

    @property
    def graph_api_root(self) -> str:
        return f"{self.graph_api_base_url.rstrip('/')}/{self.graph_api_version}"

    @property
    def dashboard_auth_enabled(self) -> bool:
        return bool(self.dashboard_username and self.dashboard_password)

    @property
    def webhook_signature_required(self) -> bool:
        return not self.allow_unsigned_webhooks

    @property
    def env_token_configured(self) -> bool:
        return bool(self.instagram_access_token)

    @property
    def webhook_ready(self) -> bool:
        return bool(self.webhook_verify_token) and bool(self.facebook_app_secret)

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=APP_NAME,
        version=APP_VERSION,
        environment=_env("APP_ENV", "development"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        instagram_access_token=_env("INSTAGRAM_ACCESS_TOKEN"),
        instagram_business_account_id=_env("INSTAGRAM_BUSINESS_ACCOUNT_ID"),
        instagram_app_id=_env("INSTAGRAM_APP_ID"),
        instagram_app_secret=_env("INSTAGRAM_APP_SECRET"),
        facebook_app_secret=_env("FACEBOOK_APP_SECRET"),
        webhook_verify_token=_env("WEBHOOK_VERIFY_TOKEN"),
        graph_api_version=_version(_env("INSTAGRAM_GRAPH_VERSION", "v23.0")),
        graph_api_base_url=_env("GRAPH_API_BASE_URL", "https://graph.facebook.com").rstrip("/"),
        graph_timeout_seconds=_float_env("GRAPH_TIMEOUT_SECONDS", 20.0),
        database_url=_env("DATABASE_URL", "sqlite:///./app.db"),
        public_base_url=_env("PUBLIC_BASE_URL").rstrip("/"),
        dashboard_username=_env("DASHBOARD_USERNAME"),
        dashboard_password=_env("DASHBOARD_PASSWORD"),
        # Off by default: signatures are mandatory unless a developer explicitly
        # opts out for local hacking (a loud warning is logged when they do).
        allow_unsigned_webhooks=_flag("ALLOW_UNSIGNED_WEBHOOKS", False),
    )
