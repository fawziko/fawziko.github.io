#!/usr/bin/env python3
"""Refresh the long-lived Instagram/Facebook User Access Token.

Long-lived tokens expire after ~60 days and cannot be refreshed once expired.
Run this before day 60 (or use the "Refresh token" button in Settings).

Usage (from the commentdm directory):
    python scripts/refresh_token.py
    python scripts/refresh_token.py --print-token
    python scripts/refresh_token.py --no-save --print-token

Requires INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET (or FACEBOOK_APP_SECRET)
in .env / the environment. By default the new token is written to the database
(the same store the dashboard uses) and never printed in full.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from config import get_settings  # noqa: E402
from database import SessionLocal, init_db  # noqa: E402
from instagram import InstagramConfigError, InstagramError, refresh_long_lived_token  # noqa: E402
from services import effective_credentials, get_or_create_config  # noqa: E402
from utils import mask_secret  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the long-lived access token.")
    parser.add_argument(
        "--print-token",
        action="store_true",
        help="Print the new token (sensitive — clear your terminal afterwards).",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write the new token to the database.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.instagram_app_id:
        print("ERROR: set INSTAGRAM_APP_ID in .env or the environment.", file=sys.stderr)
        return 2
    app_secret = settings.instagram_app_secret or settings.facebook_app_secret
    if not app_secret:
        print(
            "ERROR: set INSTAGRAM_APP_SECRET (or FACEBOOK_APP_SECRET) in .env.",
            file=sys.stderr,
        )
        return 2

    init_db()
    with SessionLocal() as db:
        current = effective_credentials(db).access_token
        if not current:
            print(
                "ERROR: no access token found in the database or environment.",
                file=sys.stderr,
            )
            return 2

        print("Exchanging the current token for a fresh 60-day token…")
        try:
            result = asyncio.run(
                refresh_long_lived_token(
                    current,
                    settings.instagram_app_id,
                    app_secret,
                    base_url=settings.graph_api_base_url,
                    api_version=settings.graph_api_version,
                    timeout=settings.graph_timeout_seconds,
                )
            )
        except InstagramConfigError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        except InstagramError as exc:
            print(f"ERROR: {exc.public_message()}", file=sys.stderr)
            print(
                "If the current token is already expired you must generate a new "
                "one in the Graph API Explorer.",
                file=sys.stderr,
            )
            return 1

        token = result.get("access_token")
        if not token:
            print("ERROR: Facebook did not return a token.", file=sys.stderr)
            return 1

        if args.no_save:
            print("--no-save: the database was not updated.")
        else:
            config = get_or_create_config(db)
            config.access_token = token
            db.commit()
            print("Saved the new token to the database (used by the dashboard).")

        expires_in = result.get("expires_in")
        if expires_in:
            print(f"Expires in {expires_in} seconds (~{round(expires_in / 86400)} days).")
        print(f"Token: {token if args.print_token else mask_secret(token)}")
        if args.print_token:
            print("Treat this value like a password. Clear shell history if needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
