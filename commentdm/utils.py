"""Small, dependency-free helpers shared across the app."""

from __future__ import annotations

import re
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite stores naive datetimes; we always use UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    """ISO-8601 with an explicit Z suffix, for JavaScript and JSON APIs."""
    if value is None:
        return None
    return ensure_utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def format_dt(value: datetime | None, *, with_time: bool = True) -> str:
    if value is None:
        return "—"
    dt = ensure_utc(value)
    if with_time:
        return dt.strftime("%d %b %Y, %H:%M UTC")
    return dt.strftime("%d %b %Y")


def format_relative(value: datetime | None) -> str:
    if value is None:
        return "Never"
    delta = datetime.now(timezone.utc) - ensure_utc(value)
    seconds = int(delta.total_seconds())
    if seconds < 45:
        return "Just now"
    if seconds < 3600:
        minutes = max(1, seconds // 60)
        return f"{minutes} min ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hr{'s' if hours != 1 else ''} ago"
    days = seconds // 86400
    if days == 1:
        return "Yesterday"
    if days < 30:
        return f"{days} days ago"
    return format_dt(value, with_time=False)


def mask_secret(value: str | None) -> str | None:
    """Never reveal a secret. Show only a short, non-sensitive suffix."""
    if not value:
        return None
    cleaned = value.strip()
    if len(cleaned) <= 8:
        return "•" * 12
    return f"{'•' * 12}{cleaned[-4:]}"


def truncate(text: str | None, limit: int = 160) -> str:
    if not text:
        return ""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= limit:
        return flat
    return flat[: max(0, limit - 1)].rstrip() + "…"


def clean_error(message: object, limit: int = 900) -> str:
    """Flatten an error for storage; access tokens are masked defensively."""
    text = re.sub(r"\s+", " ", str(message)).strip()
    text = re.sub(r"(access_token=)[^&\s]+", r"\1[redacted]", text)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._\-]+", r"\1[redacted]", text)
    return truncate(text, limit)


def start_of_utc_day(value: datetime | None = None) -> datetime:
    dt = ensure_utc(value or utcnow())
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
