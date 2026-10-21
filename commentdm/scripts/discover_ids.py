#!/usr/bin/env python3
"""Find the Facebook Page ID and Instagram Business Account ID for a token.

Usage (from the commentdm directory):
    python scripts/discover_ids.py

The token is read from the database first, then INSTAGRAM_ACCESS_TOKEN.
It requires pages_show_list (and a token created for the right Facebook app and
Page). Nothing is printed except IDs, names and a reminder.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from config import get_settings  # noqa: E402
from database import SessionLocal, init_db  # noqa: E402
from services import effective_credentials  # noqa: E402


def main() -> int:
    settings = get_settings()
    init_db()
    with SessionLocal() as db:
        token = effective_credentials(db).access_token
    if not token:
        print(
            "ERROR: no access token. Set INSTAGRAM_ACCESS_TOKEN or save one in Settings.",
            file=sys.stderr,
        )
        return 2

    url = f"{settings.graph_api_base_url}/{settings.graph_api_version}/me/accounts"
    try:
        response = httpx.get(
            url,
            params={
                "fields": "id,name,instagram_business_account{id,username}",
                "access_token": token,
            },
            timeout=settings.graph_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        print(f"ERROR: could not reach the Graph API ({exc.__class__.__name__}).", file=sys.stderr)
        return 1

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        error = (payload or {}).get("error") or {}
        print(
            "Graph API error: "
            + (error.get("error_user_msg") or error.get("message") or str(response.status_code)),
            file=sys.stderr,
        )
        print(
            "Make sure the token was created with pages_show_list and that you "
            "granted access to the Facebook Page linked to the Instagram account.",
            file=sys.stderr,
        )
        return 1

    pages = payload.get("data") or []
    if not pages:
        print(
            "No Facebook Pages were returned. Link a Page to the Instagram "
            "professional account and regenerate the token with pages_show_list.",
            file=sys.stderr,
        )
        return 1

    print("Facebook Pages found:\n")
    for page in pages:
        instagram = page.get("instagram_business_account") or {}
        print(f"  Page: {page.get('name')}")
        print(f"    FACEBOOK PAGE ID:            {page.get('id')}")
        if instagram.get("id"):
            print(f"    INSTAGRAM BUSINESS ACCOUNT:  {instagram['id']}")
            if instagram.get("username"):
                print(f"    Instagram username:          @{instagram['username']}")
        else:
            print("    (no Instagram professional account linked to this Page)")
        print("")

    print("Copy the IDs into .env or the dashboard Settings form.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
