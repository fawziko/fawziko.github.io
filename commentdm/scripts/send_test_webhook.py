#!/usr/bin/env python3
"""Send a correctly signed fake Instagram comment webhook to a running app.

Useful for validating the webhook route, signature check, matching and dedupe
without waiting for a real comment. Note: if the campaign matches, the app will
try to call Instagram with the fake comment ID — the real API will reject it, and
the attempt is recorded in Activity as failed. That is expected.

Usage (from the commentdm directory):
    python scripts/send_test_webhook.py --post-id 17895695668004550 --text "price please"
    python scripts/send_test_webhook.py --url https://your-app.example/webhook/instagram \
        --post-id 17895695668004550 --text "how much" --comment-id my-test-1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from config import get_settings  # noqa: E402
from security import compute_signature  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a signed test comment webhook.")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/webhook/instagram",
        help="Webhook endpoint (default: local dev server).",
    )
    parser.add_argument("--post-id", required=True, help="Tracked Instagram media ID.")
    parser.add_argument("--text", default="price please", help="Comment text.")
    parser.add_argument(
        "--comment-id",
        default=f"test_comment_{int(time.time())}",
        help="Unique comment ID. Reuse it to verify deduplication.",
    )
    parser.add_argument("--username", default="test_commenter")
    parser.add_argument("--account-id", default="", help="Instagram account ID for entry.id.")
    parser.add_argument("--unsigned", action="store_true", help="Skip the signature (dev only).")
    args = parser.parse_args()

    settings = get_settings()
    account_id = args.account_id or settings.instagram_business_account_id or "17841400000000000"
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": account_id,
                "time": int(time.time()),
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": args.comment_id,
                            "text": args.text,
                            "media": {"id": args.post_id},
                            "from": {"id": "987654321", "username": args.username},
                        },
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()
    headers = {"content-type": "application/json"}

    if not args.unsigned:
        if not settings.facebook_app_secret:
            print(
                "ERROR: FACEBOOK_APP_SECRET is empty. Set it in .env or pass --unsigned.",
                file=sys.stderr,
            )
            return 2
        headers["X-Hub-Signature-256"] = compute_signature(
            settings.facebook_app_secret, body
        )

    print(f"POST {args.url}  comment={args.comment_id}  text={args.text!r}")
    try:
        response = httpx.post(args.url, content=body, headers=headers, timeout=30)
    except httpx.HTTPError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"HTTP {response.status_code}")
    print(response.text)
    if response.status_code == 200:
        print(
            "Accepted. Open /dashboard/activity to see whether a campaign matched "
            "and what the Graph API said (expect an error for a fake comment ID)."
        )
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
