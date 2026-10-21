# CommentDM

**Instagram comment → public reply → private DM, automatically.**

CommentDM is a self-hosted, ManyChat-style automation tool for Instagram professional accounts. When someone comments a tracked keyword on a post or Reel you choose, CommentDM replies publicly under the comment and sends that person a private reply (DM).

It is built with **FastAPI, SQLite/SQLAlchemy, Jinja2 and vanilla JavaScript**, runs as a single Docker container, and uses **only the official Instagram Graph API** — no Selenium, no unofficial Instagram APIs, no browser automation.

> This app lives in the `commentdm/` directory of this repository. The portfolio site at the repository root is a separate static site and is unaffected.

```
 Instagram user comments "price"
              │
              ▼
 Meta webhook  ──POST /webhook/instagram (X-Hub-Signature-256 verified)──▶  CommentDM
                                                                               │
                     ┌─────────────────────────────────────────────────────────┤
                     │ match active campaign (post ID + keyword, dedupe)        │
                     ▼                                                         ▼
      POST /{comment-id}/replies                          POST /{ig-user-id}/messages
      public reply under the comment                      private reply → recipient.comment_id
                     │                                                         │
                     └───────────────────────┬─────────────────────────────────┘
                                             ▼
                                  Activity log (SQLite)
```

---

## Table of contents

1. [Features](#features)
2. [Read this first: Instagram DM rules](#read-this-first-instagram-dm-rules)
3. [Quick start](#quick-start)
4. [Complete Instagram / Facebook setup guide](#complete-instagram--facebook-setup-guide)
5. [Getting a Post ID for a specific Reel or video](#getting-a-post-id-for-a-specific-reel-or-video)
6. [How matching, dedupe and delivery work](#how-matching-dedupe-and-delivery-work)
7. [Configuration reference](#configuration-reference)
8. [Dashboard & API reference](#dashboard--api-reference)
9. [Project structure](#project-structure)
10. [Deployment](#deployment)
11. [Security](#security)
12. [Token refresh (60-day expiry)](#token-refresh-60-day-expiry)
13. [Database & moving to Postgres](#database--moving-to-postgres)
14. [Testing](#testing)
15. [Troubleshooting](#troubleshooting)
16. [Limitations & possible next steps](#limitations--possible-next-steps)

---

## Features

- **Webhook receiver** at `GET/POST /webhook/instagram`
  - Echoes `hub.challenge` during Meta's verification handshake.
  - Validates **`X-Hub-Signature-256`** with your app secret on every POST.
  - Ignores replies-to-comments, the business's own comments, and events from other Instagram accounts.
- **Public comment reply + private DM** for every matching comment.
- **Campaign rules** linking one Instagram post ID to many keywords and two messages (public reply and DM).
- **Case-insensitive, partial keyword matching**; the longest matching keyword wins.
- **Deduplication** with a unique `comment_id` ledger committed *before* the API calls, so Meta retries cannot double-fire.
- **API resilience** — rate limits (HTTP 429 and Graph codes 4/17/32/613) retry with exponential backoff and jitter; all responses are logged safely.
- **Dashboard** with campaigns, activity log, environment health and settings.
- **Post preview** fetched from the Graph API and cached with the campaign.
- **Simulation / dry-run** test per campaign — no Instagram API call, recorded in Activity.
- **One-click webhook subscription** (`POST /{ig-id}/subscribed_apps`) and **one-click token refresh**.
- **Optional dashboard Basic auth**, strict CSP, no secrets in the frontend.
- **Docker + Railway + Render** deployment files and a `/health` endpoint.

---

## Read this first: Instagram DM rules

Instagram does **not** allow an app to send a normal DM to anyone at any time. Before you build expectations or apply for permissions, understand the two mechanisms:

| | Standard DM | **Private reply** (used by this app) |
|---|---|---|
| Endpoint | `POST /{ig-user-id}/messages` with `recipient.id` | `POST /{ig-user-id}/messages` with `recipient.comment_id` |
| Who can be messaged | Only someone who messaged the business first | Anyone who commented on your post/Reel |
| Time window | 24 hours from their last message (or approved tags) | 7 days from the comment |
| Messages allowed | As many as the window allows | **Exactly one per comment** |
| Permission | `instagram_manage_messages` | `instagram_manage_messages` (plus comments access) |
| Rate limit | Send API limits | 750 private replies/hour/account (100/sec for Live comments) |

**What CommentDM does:** it sends the private reply to the comment ID, which is the only sanctioned way to move a commenter into the inbox without them messaging you first. This is why the feature exists — but it still requires:

1. **`instagram_manage_messages` with Advanced Access / an approved use case.** In Development mode, only app admins/testers can exercise it. For real users, submit the permission in **App Review** (see [Going live](#step-9--switch-the-app-to-live-and-pass-app-review)).
2. The comment must be **less than 7 days old**, still exist, and not be on an unsupported surface.
3. The business must not have already sent a private reply to that comment. A second attempt returns Graph subcode `2534014`, which the dashboard shows as **Already sent**.

**What it cannot do:** it cannot send follow-up messages, broadcast to people who never commented, or keep messaging after the 7-day window unless the user replies to the DM first (which opens the normal 24-hour conversation window). Multi-message drip sequences are intentionally out of scope.

If the private reply fails and the commenter already has an open DM thread, CommentDM makes one fallback attempt with a standard DM (`recipient.id`). Otherwise the failure is recorded in Activity with the exact Meta error code.

**How to apply for the permission**

1. In the Meta app dashboard, complete **App Review → Permissions and Features** for `instagram_manage_messages`, `instagram_manage_comments`, `pages_manage_metadata`, `instagram_basic`, `pages_show_list`, and `pages_read_engagement`.
2. Request **Advanced Access** for the Instagram permissions (Standard Access is not enough for accounts that are not connected to your app).
3. Provide a screencast showing: connecting an account, creating a keyword campaign, a comment arriving, the public reply, and the private reply in the inbox.
4. Provide a public privacy policy URL and data-deletion instructions.
5. Complete **Business Verification** in Meta Business Suite if prompted.
6. Switch the app to **Live** mode. Webhooks and permissions behave differently in Development mode: only users with a role on the app can grant permissions, and events for other accounts are not delivered.

Meta references: [Instagram Platform overview](https://developers.facebook.com/docs/instagram-platform/overview/), [Private replies](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/messages/), [Permissions reference](https://developers.facebook.com/docs/permissions/reference).

---

## Quick start

### Requirements

- Python **3.11+** (Docker image uses 3.12)
- No Node.js, no build step
- Optional: Docker 24+

### Run locally

```bash
cd commentdm

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt
cp .env.example .env
```

Generate a verify token and put it in `.env` (or leave it blank for now and use the demo):

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Start the app **from the `commentdm/` directory** (imports are app-relative):

```bash
uvicorn main:app --reload --port 8000
```

Open:

| URL | Purpose |
|---|---|
| http://localhost:8000/dashboard | Campaigns dashboard |
| http://localhost:8000/dashboard/activity | Delivery log |
| http://localhost:8000/dashboard/settings | Credentials & webhook setup |
| http://localhost:8000/health | Health check → `{"status": "ok"}` |
| http://localhost:8000/docs | OpenAPI docs |

On a fresh install you can click **Load sample data** to explore the UI. Sample campaigns are prefixed with `Sample —` and sample activity is marked **Simulated**; no Instagram API calls are made. Remove them with the delete buttons (or delete `app.db`) when you are ready to connect a real account.

### Docker

```bash
cd commentdm
docker build -t commentdm .
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e DATABASE_URL=sqlite:////data/app.db \
  -e PUBLIC_BASE_URL=http://localhost:8000 \
  -v commentdm-data:/data \
  commentdm
```

`-e DATABASE_URL=…` comes **after** `--env-file` on purpose: `.env.example` ships `DATABASE_URL=sqlite:///./app.db` for local runs, which inside the container points at the image layer instead of the volume. The override keeps the database on `/data/app.db` so it survives restarts.

The container runs as a non-root user after fixing volume ownership, and `/health` is used by the Docker health check and by Railway/Render.

---

## Complete Instagram / Facebook setup guide

This walkthrough assumes **you do not have a Facebook Developer app yet**. Meta's dashboard wording changes occasionally; the sequence and permission names below are current for 2026.

### Prerequisites

- An Instagram account you can switch to **Business** or **Creator**.
- A Facebook account that administers the Facebook Page linked to that Instagram account.
- A publicly reachable **HTTPS** URL for this app (Railway/Render domain, or a tunnel for local development).
- About 20 minutes for development-mode testing; App Review can take days.

### Step 1 — Convert Instagram to a professional account

1. In the Instagram app: **Settings and privacy → Account type and tools → Switch to professional account**.
2. Choose **Business** or **Creator**. Both work with the Graph API; Business is the most common for automation.
3. Connect a Facebook Page: **Edit profile → Page**, or **Settings → Business tools and controls → linked accounts**, and select/create a Page.
   - If you have no Page: create one at <https://www.facebook.com/pages/create>.
   - The Facebook user generating the token must be an **admin** of this Page.
4. Make sure the Instagram account is **public** if you want comments from non-followers to arrive.

Meta guide: [Convert to a professional account](https://help.instagram.com/502981923235522).

### Step 2 — Create a Facebook Developer app

1. Go to <https://developers.facebook.com/> and log in with the Facebook account that administers the Page.
2. Click **My Apps → Create app**.
3. Name the app (e.g. `CommentDM`), enter a contact email, then choose:
   - Use case: **Other**
   - App type: **Business**
   - Click **Create app** (Facebook may ask you to re-enter your password).
4. On the app dashboard, **Add product → Instagram**. Add the **Instagram Graph API** / **Instagram API with Facebook Login** product. Also add **Facebook Login for Business** if the dashboard prompts for it (used by the token flow).
5. Open **App settings → Basic**:
   - Copy **App ID** → `INSTAGRAM_APP_ID` (also used by the token refresh feature).
   - Copy **App Secret** → `FACEBOOK_APP_SECRET` **and** `INSTAGRAM_APP_SECRET` (the refresh endpoint needs the secret; the webhook needs the app secret).
   - Add your app domain, privacy policy URL and terms of service URL (required later for Live mode).
6. Keep the app in **Development** mode for now. Add your test Instagram/Facebook users under **App roles → Roles** (Administrator/Tester) so they can grant permissions before App Review.

> Never put the app secret in frontend code. It is read from the server environment and used only for HMAC verification and token exchange.

### Step 3 — Add the required permissions

In the app dashboard and in the Graph API Explorer, request:

| Permission | Why it is needed |
|---|---|
| `instagram_basic` | Read the Instagram professional account and media. |
| `instagram_manage_comments` | Read and reply to comments (the public reply). |
| `instagram_manage_messages` | Send the private reply / DM. **Requires approval for real users.** |
| `pages_show_list` | Discover the Facebook Page linked to Instagram. |
| `pages_read_engagement` | Read Page engagement data used by the Instagram connection. |
| `pages_manage_metadata` | Subscribe the Page/app to webhook updates. Required for reliable webhook delivery outside admin/tester accounts. |
| `business_management` *(optional)* | Some Business Manager setups need it to see the Page/IG account. |
| `pages_read_user_content` *(optional)* | Some comment-read variants request it. |

For Development-mode testing, these can be granted without App Review. **For anyone who is not an admin/tester of your app, most of these require Advanced Access in App Review** — see [Step 9](#step-9--switch-the-app-to-live-and-pass-app-review).

### Step 4 — Find your Page ID and Instagram Business Account ID

Use the **Graph API Explorer** (<https://developers.facebook.com/tools/explorer/>):

1. Select your app in **Meta App**.
2. Open **User or Page → Get User Access Token** and tick the permissions from Step 3.
3. Click **Generate Access Token**, log in, and grant access to the correct Page and Instagram account.
4. Run:

```
GET /me/accounts?fields=id,name,instagram_business_account{id,username}
```

The response looks like:

```json
{
  "data": [
    {
      "id": "100000000000000",
      "name": "Fawziko Studio",
      "instagram_business_account": {
        "id": "17841400000000000",
        "username": "fawziko.studio"
      }
    }
  ]
}
```

- `id` → **Facebook Page ID** → the `page_id` field in Settings.
- `instagram_business_account.id` → **Instagram Business Account ID** → `INSTAGRAM_BUSINESS_ACCOUNT_ID`. These two IDs are different.

You can also run the helper script (it reads the token from the database or env and never prints it):

```bash
python scripts/discover_ids.py
```

Or query `GET /{page-id}?fields=instagram_business_account{id,username}` directly.

### Step 5 — Generate a long-lived User Access Token

The Graph API Explorer creates a **short-lived** user token (about 1–2 hours). Exchange it for a **long-lived** token (about 60 days):

1. In Graph API Explorer, copy the generated token.
2. Call this endpoint (Graph API Explorer or `curl`):

```
GET /oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={your-app-id}
  &client_secret={your-app-secret}
  &fb_exchange_token={short-lived-token}
```

Example with `curl`:

```bash
curl -s "https://graph.facebook.com/v23.0/oauth/access_token" \
  --get \
  --data-urlencode "grant_type=fb_exchange_token" \
  --data-urlencode "client_id=$INSTAGRAM_APP_ID" \
  --data-urlencode "client_secret=$INSTAGRAM_APP_SECRET" \
  --data-urlencode "fb_exchange_token=$SHORT_LIVED_TOKEN"
```

The response contains `access_token` and `expires_in` (seconds; 60 days ≈ 5,184,000).

3. Save it **either**:
   - in **Dashboard → Settings → Instagram credentials → Long-lived User Access Token** (recommended; stored in the database), or
   - as `INSTAGRAM_ACCESS_TOKEN` in `.env` / your host's variables.

   A token saved in the dashboard overrides the environment variable. The raw token is never re-displayed by the app; you will only see a masked suffix.

4. Click **Test connection** in Settings. A successful call shows the Instagram username and follower count and saves the username for the sidebar.

**Token facts**

- Long-lived User tokens last ~60 days. Treat the expiry date as a deadline.
- The refresh endpoint (`fb_exchange_token`) can refresh a token **before** it expires. It does **not** work after expiry.
- Refresh from the dashboard (**Settings → Refresh token**, needs `INSTAGRAM_APP_ID` + `INSTAGRAM_APP_SECRET`) or run:

  ```bash
  python scripts/refresh_token.py
  python scripts/refresh_token.py --print-token   # only if you need the raw value
  ```

- A cron job is a reliable safety net:

  ```cron
  0 3 1 * * cd /path/to/commentdm && /path/to/.venv/bin/python scripts/refresh_token.py >> /var/log/commentdm-refresh.log 2>&1
  ```

  The script masks the token by default and saves it to the database.

- If the token is leaked, remove it in Settings immediately, regenerate in the Graph API Explorer, and rotate the app secret if necessary.

### Step 6 — Configure the webhook

Meta must be able to reach this app over public HTTPS. Deploy it first, or use a tunnel such as `ngrok http 8000` / `cloudflared tunnel --url http://localhost:8000` for local testing.

1. Set `PUBLIC_BASE_URL` on the server to the public origin, e.g. `https://commentdm-production.up.railway.app` (no trailing slash). The Settings page uses it to display the callback URL. If it is blank, the page falls back to the browser's current origin.
2. Put a long random value in `WEBHOOK_VERIFY_TOKEN` and restart the app.
3. In the Meta app dashboard: **Webhooks → Instagram** (or **Instagram Graph API → Webhooks**) → **Subscribe to this object**.
4. Enter:
   - **Callback URL:** `https://YOUR-DOMAIN/webhook/instagram`
   - **Verify token:** the exact value of `WEBHOOK_VERIFY_TOKEN`
5. Click **Verify and save**. Meta sends `GET /webhook/instagram?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...`; the app returns the raw challenge with HTTP 200. A failure here means the URL/token is wrong or the app is not publicly reachable.
6. Subscribe to the **`comments`** field. Optionally subscribe to `messages` if you plan to read inbound DMs (this app only needs `comments`; it sends DMs but does not process inbound message events).
7. **Subscribe the Instagram account itself.** Configuring the app-level webhook is not enough — the IG account must be subscribed to your app. The easiest way is **Dashboard → Settings → Subscribe comment webhooks**, which calls:

   ```
   POST /{ig-user-id}/subscribed_apps?subscribed_fields=comments,messages
   ```

   You can do the same in the Graph API Explorer with your User token. The response lists the subscribed fields. This call needs the Instagram permissions (and `pages_manage_metadata` for Page-level reliability).
8. Send a test comment from a **different Instagram account** on a tracked post. Watch **Activity** and the Meta webhook delivery log.

Local development notes:

- Meta requires a public HTTPS URL. An `http://localhost` URL will fail verification.
- Tunnels change URL when restarted; update both `PUBLIC_BASE_URL` and the callback URL in Meta each time.
- To test signatures without Meta, use `scripts/send_test_webhook.py` (see [Testing](#testing)).

Webhook payload handling:

- The receiver validates `X-Hub-Signature-256` with `FACEBOOK_APP_SECRET` using a constant-time comparison. Invalid or missing signatures receive **403**.
- Unsigned payloads are rejected unless you explicitly set `ALLOW_UNSIGNED_WEBHOOKS=true` for local hacking (never in production).
- The handler returns HTTP 200 immediately and does the two Graph API calls in a background task, so Meta does not retry while Instagram is slow.
- Events for other IG accounts are skipped when your account ID is configured.
- Replies to comments (`parent_id`) are skipped to avoid replying to your own reply loops and double-DMs.
- Every processed comment is written to the dedupe table **before** any API call.

### Step 7 — Get a Post ID (covered in detail below)

Copy the numeric media ID of the target Reel/post and paste it into the campaign's **Instagram post ID** field. Click **Preview** to verify the thumbnail and caption.

### Step 8 — Create a campaign and run a real test

1. **Settings:** save the token + Instagram Business Account ID, click **Test connection**.
2. **Settings → Subscribe comment webhooks** (or use the Graph API Explorer call above).
3. **Campaigns → New campaign:**
   - Post ID (numeric, from Step 7)
   - Keywords, comma-separated, e.g. `price, pricing, how much`
   - Public comment reply, e.g. `Just sent it to your DMs 💌`
   - DM message, e.g. `Hey! Here's the price list…`
   - Leave **Campaign active** checked.
4. Click the **play** button on the campaign card to run a **dry-run test**. It checks matching and shows the exact messages without calling Instagram; the run is logged as **Simulated**.
5. From a **different Instagram account**, comment one of the keywords on the post. You should see:
   - a public reply under the comment,
   - the private reply in the commenter's DM inbox (or Requests folder),
   - a **Delivered** row in **Activity** with both deliveries marked **Sent**.
6. Meta may retry webhooks. Post the same event twice with `scripts/send_test_webhook.py --comment-id same-id` and confirm only one Activity row appears.

If nothing happens, see [Troubleshooting](#troubleshooting).

### Step 9 — Switch the app to Live and pass App Review

Development mode lets you test only with Facebook/Instagram accounts that have a role on the app. To serve real users:

1. **App Review → Permissions and Features** → request **Advanced Access** for:
   - `instagram_basic`
   - `instagram_manage_comments`
   - `instagram_manage_messages`
   - `pages_show_list`
   - `pages_read_engagement`
   - `pages_manage_metadata`
2. Submit the required screencast and description. Explain the comment-to-DM use case and that DMs are only sent as private replies to the commenter.
3. Fill in **App settings → Basic**: privacy policy URL, terms of service, data deletion callback/instructions, app icon, category.
4. Complete **Business Verification** if requested.
5. Toggle the app to **Live** at the top of the dashboard.
6. Re-subscribe the accounts (`subscribed_apps`) after switching modes — subscriptions can be lost or inactive.
7. Re-test with a non-tester account.

Meta's review requirements change; always follow the checklist shown in the dashboard.

---

## Getting a Post ID for a specific Reel or video

The **Post ID is the numeric media ID**, not the shortcode in the Instagram URL (`/reel/C8xYzAbCdEf/` is a shortcode and will **not** work).

### Option A — List your media (best for Reels)

In the Graph API Explorer, with a User token that has `instagram_basic` and the correct account selected:

```
GET /{ig-user-id}/media?fields=id,caption,media_type,media_product_type,permalink,thumbnail_url,timestamp&limit=50
```

- `media_type` will be `VIDEO` for videos/Reels.
- `media_product_type` will be `REELS` for Reels (and `FEED` for regular posts).
- Find the item by its caption or `permalink`, then copy the numeric `id`.
- For a Reel, the `permalink` looks like `https://www.instagram.com/reel/…/` and matches what you see in the app.

### Option B — Look up a media ID directly

If you already have an ID from a previous run, verify it:

```
GET /{media-id}?fields=id,caption,media_type,media_product_type,thumbnail_url,permalink,timestamp,comments_count
```

In the dashboard, paste the ID and click **Preview**; the app calls this endpoint and shows the thumbnail/caption. This is the fastest confirmation that the ID belongs to your account and is accessible.

### Option C — Use a script

The helper scripts only fetch IDs; they never post anything:

```bash
# Page + IG account IDs
python scripts/discover_ids.py

# Post details using a known media ID (Graph API Explorer or curl)
curl -s "https://graph.facebook.com/v23.0/1300000000000000\
?fields=id,caption,media_type,media_product_type,permalink,thumbnail_url\
&access_token=$INSTAGRAM_ACCESS_TOKEN"
```

### Common mistakes

- Pasting the URL or shortcode instead of the media ID → validation rejects it (it must be 5–30 digits).
- Using another account's post: you can only automate comments on **your own** professional account's media.
- Using a photo ID for a Reel, or an old API ID that has been deleted → the preview returns a Graph error.
- Using a post from a **different Instagram account** than the configured `INSTAGRAM_BUSINESS_ACCOUNT_ID` → the token cannot reply to comments there.

---

## How matching, dedupe and delivery work

### Matching

A comment is actionable only if:

1. It is a **top-level** comment (no `parent_id`).
2. It was not authored by the business account itself.
3. Its `media.id` exactly equals an **active** campaign's `post_id`.
4. At least one keyword is a **case-insensitive substring** of the comment. Whitespace is normalized, so `how   much` matches `how much`.
5. It has never been processed before (see dedupe).

If several active campaigns match the same post/comment, the **longest keyword** wins; ties go to the newer campaign. Keywords are de-duplicated when saved and shown as chips in the UI.

### Deduplication

`processed_comments.comment_id` has a **unique index**. CommentDM inserts a `processing` row and commits it *before* calling Instagram. If Meta retries, the second insert raises a unique constraint and the event is ignored. This is crash-safe: a process restart cannot re-fire the same comment.

The same table is the Activity log. **Deleting the log also deletes the dedupe ledger.** Re-delivered old events could then trigger again. This is called out in the confirmation dialog.

### Delivery and statuses

| Status | Meaning |
|---|---|
| `processing` | Row inserted; API calls in progress (a crash can leave a row here). |
| `success` | Public reply sent and DM delivered (or previously delivered by another tool). |
| `partial` | One of the two actions succeeded. |
| `failed` | Neither succeeded; `error_detail` explains why. |
| `simulated` | A dry run from the Test button. No API call. Excluded from stats. |

Per-channel states are `sent`, `already_sent`, `failed`, `pending`, `simulated`. `already_sent` means Graph returned subcode `2534014` (one private reply per comment).

### Rate limits and retries

- The Graph API retries up to **3 times** on HTTP 429 / 5xx, Graph codes 4, 17, 32, 613 (throttling), and transient network errors, with 1s, 2s, 4s backoff plus jitter. After that, the failure is recorded and the dashboard shows the error. Network failures therefore take a few seconds to surface in the Settings connection test.
- A public reply is **not** retried on non-rate-limit errors.
- If a private reply fails and the commenter's ID is known, one standard-DM fallback is attempted (usually only succeeds if an existing conversation is open).
- Private replies are limited to **750/hour per account** (post/Reel comments). If you run high-volume campaigns, expect throttling; a durable queue with scheduled retries is a future enhancement.

### Webhook semantics

- Meta expects a fast 2xx. Processing happens after the response.
- FastAPI `BackgroundTasks` run in-process. If the container dies mid-process, the comment may be left `processing`; it will not be retried automatically. Add a durable queue (Redis/RQ/Celery) if you need at-least-once processing at scale.
- Webhook events do not include the full comment data in all cases; this app reads what Meta sends (`text`, `media.id`, `from.id`, `from.username`). If a field is missing it is simply not matched.
- The webhook can be replayed by anyone who possesses a valid signature and body; dedupe protects you (unless you clear the ledger).

---

## Configuration reference

Copy `.env.example` to `.env`. Values saved in the dashboard override the corresponding env value for the token and IDs.

| Variable | Required | Default | Description |
|---|---|---|---|
| `INSTAGRAM_ACCESS_TOKEN` | yes* | — | Long-lived Facebook User Access Token. *Can be saved in Settings instead.* |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | yes* | — | Instagram professional account ID (numeric). *Can be saved in Settings.* |
| `FACEBOOK_APP_SECRET` | yes | — | Validates webhook signatures. Without it webhooks are rejected. |
| `WEBHOOK_VERIFY_TOKEN` | yes | — | The string entered in Meta's webhook screen. |
| `DATABASE_URL` | no | `sqlite:///./app.db` | SQLAlchemy URL. Relative SQLite paths are anchored to `commentdm/`. |
| `PUBLIC_BASE_URL` | recommended | — | Public HTTPS origin, no trailing slash. Used to show the callback URL. |
| `INSTAGRAM_APP_ID` | optional | — | Enables the token refresh endpoint/button. |
| `INSTAGRAM_APP_SECRET` | optional | falls back to `FACEBOOK_APP_SECRET` | Used for token refresh. |
| `INSTAGRAM_GRAPH_VERSION` | no | `v23.0` | Graph API version. |
| `GRAPH_API_BASE_URL` | no | `https://graph.facebook.com` | Change only for compatible proxies. |
| `GRAPH_TIMEOUT_SECONDS` | no | `20` | Per-request timeout. |
| `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` | strongly recommended | — | Enables HTTP Basic auth for `/dashboard` and `/api`. Both must be set. |
| `APP_ENV` | no | `development` | `production` enables startup warnings for insecure defaults. |
| `LOG_LEVEL` | no | `INFO` | Python log level. |
| `ALLOW_UNSIGNED_WEBHOOKS` | no | `false` | **Insecure.** Accept unsigned webhooks when no app secret is set. Local testing only. |

Example `.env` (the same keys requested in the project brief):

```dotenv
INSTAGRAM_ACCESS_TOKEN=
INSTAGRAM_BUSINESS_ACCOUNT_ID=
FACEBOOK_APP_SECRET=
WEBHOOK_VERIFY_TOKEN=
DATABASE_URL=sqlite:///./app.db
```

Additional variables used by deployment and optional features are documented in `.env.example`.

### Credential precedence

1. Values saved in **Settings** (database) win.
2. Environment values are the fallback.
3. The Settings API returns only `has_access_token` and a masked suffix — never the token.

If you rotate the token in Settings, the app clears the cached Instagram username until the next connection test.

---

## Dashboard & API reference

All HTML pages and REST endpoints are protected by HTTP Basic auth when `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` are set. Webhooks use the Meta signature instead.

### Pages

| Page | Path | What it does |
|---|---|---|
| Campaigns | `/dashboard` | Stats, campaign cards, search, create/edit modal, test, toggle, delete, recent activity. |
| Activity | `/dashboard/activity` | Full delivery log with search, status/campaign filters, error details, clear log. |
| Settings | `/dashboard/settings` | Credentials, connection test, webhook URL, subscription, token refresh, environment health. |
| Health | `/health` | `{"status":"ok"}` for load balancers. |
| API docs | `/docs` | OpenAPI UI (schema only; actions still require auth). |

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Public health check. |
| GET | `/webhook/instagram` | Meta verification challenge. |
| POST | `/webhook/instagram` | Signed comment events. |
| GET | `/api/config` | Safe credential state (masked). |
| PUT | `/api/config` | Save token / Page ID / IG account ID / clear token. |
| POST | `/api/config/test` | Validate credentials and cache the Instagram username. |
| POST | `/api/config/subscribe` | `POST /{ig-id}/subscribed_apps` with `comments,messages`. |
| POST | `/api/config/refresh-token` | Exchange the stored token for a fresh 60-day token. |
| GET | `/api/campaigns` | List campaigns. |
| POST | `/api/campaigns` | Create campaign (optionally fetches post preview). |
| GET | `/api/campaigns/{id}` | Fetch one. |
| PUT | `/api/campaigns/{id}` | Update (re-fetches the preview if the post ID changed). |
| DELETE | `/api/campaigns/{id}` | Delete (activity is retained, FK nulled). |
| POST | `/api/campaigns/{id}/toggle` | Activate/pause. |
| POST | `/api/campaigns/{id}/simulate` | Dry run with a sample comment. |
| POST | `/api/posts/preview` | Fetch caption/thumbnail/permalink from Graph, with cache fallback. |
| GET | `/api/activity` | Activity feed (`limit`, `status`, `campaign_id`). |
| DELETE | `/api/activity` | Clear the log and dedupe ledger. |
| GET | `/api/stats` | Dashboard counters. |
| POST | `/api/demo/seed` | Load sample data only when no campaigns exist. |

### Example requests

```bash
# Public health check
curl -s http://localhost:8000/health

# With Basic auth enabled
curl -s -u "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" \
  http://localhost:8000/api/campaigns

# Create a campaign
curl -s -u "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" \
  -X POST http://localhost:8000/api/campaigns \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Pricing reel",
    "post_id": "17895695668004550",
    "keywords": "price, pricing, how much",
    "comment_reply": "Just sent it to your DMs 💌",
    "dm_message": "Hey! Here is the price list you asked for.",
    "is_active": true
  }'

# Dry-run a comment against a campaign
curl -s -u "$DASHBOARD_USERNAME:$DASHBOARD_PASSWORD" \
  -X POST http://localhost:8000/api/campaigns/1/simulate \
  -H 'Content-Type: application/json' \
  -d '{"comment_text": "what is the price?", "commenter_username": "lina.creates"}'
```

Validation errors return HTTP 422 with a single readable `detail` string plus an `errors` array. Duplicate comment IDs are absorbed silently by the webhook path (they are not 4xx errors).

---

## Project structure

```
commentdm/
├── main.py                      # FastAPI app, lifespan, security headers, /health
├── config.py                    # Env loading (python-dotenv) + settings
├── database.py                  # SQLAlchemy engine/session, SQLite pragmas, init_db
├── models.py                    # Config, Campaign, ProcessedComment
├── schemas.py                   # Pydantic request validation
├── instagram.py                 # Official Graph API client (replies, DMs, media, retry)
├── services.py                  # Matching, dedupe, processing, stats, demo data
├── keywords.py                  # Keyword parsing/matching helpers
├── security.py                  # X-Hub-Signature-256 + optional Basic auth
├── utils.py                     # UTC/time, masking, truncation
├── routes/
│   ├── webhook.py               # GET/POST /webhook/instagram
│   ├── dashboard.py             # Jinja2 pages
│   └── api.py                   # REST API
├── templates/                   # Jinja2: base, campaigns, activity, settings, macros
│   ├── base.html
│   ├── campaigns.html
│   ├── activity.html
│   ├── settings.html
│   ├── _ui.html
│   ├── _icons.html
│   └── _confirm_dialog.html
├── static/
│   ├── css/app.css              # Full dashboard design system (no CDN)
│   └── js/                      # app.js, campaigns.js, activity.js, settings.js
├── scripts/
│   ├── refresh_token.py         # 60-day token refresh (DB-aware)
│   ├── discover_ids.py          # Page + IG account IDs
│   └── send_test_webhook.py     # Signed fake webhook for local tests
├── tests/                       # 66 pytest tests, Graph API mocked
├── .env.example
├── .dockerignore / .gitignore
├── Dockerfile / docker-entrypoint.sh
├── railway.toml
├── render.yaml
├── requirements.txt / requirements-dev.txt
└── README.md
```

The app is **not** a Python package; run it from this directory (`uvicorn main:app`) so absolute imports resolve. The Docker image does the same.

---

## Deployment

The app is a single stateless web process **except** for SQLite and the in-process background task runner. For production, either mount a persistent disk for SQLite or point `DATABASE_URL` at Postgres.

### Environment checklist

Set these on the host:

- `FACEBOOK_APP_SECRET`
- `WEBHOOK_VERIFY_TOKEN`
- `PUBLIC_BASE_URL` (after the public domain is known)
- `DATABASE_URL` (default `/data/app.db` in Docker)
- `INSTAGRAM_APP_ID` and `INSTAGRAM_APP_SECRET` (token refresh)
- `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`
- `APP_ENV=production`

The Instagram token/account ID can be saved in the dashboard after the first deploy instead of being placed in env vars.

### Railway

1. Push this repository to GitHub and create a Railway project: **New Project → Deploy from GitHub repo**.
2. Open the service → **Settings → Source → Root Directory** and set it to `commentdm`. Railway will use `commentdm/railway.toml` and the Dockerfile.
3. **Settings → Networking → Generate Domain** (HTTPS is automatic). Copy the domain.
4. Add a **Volume** mounted at `/data` (SQLite persistence). Keep one replica while using SQLite.
5. Add the variables above (`PUBLIC_BASE_URL` = `https://your-domain`).
6. Deploy. Railway checks `/health` and restarts on failure.
7. Verify `https://your-domain/health` and open `/dashboard/settings`. Configure Meta's webhook with `https://your-domain/webhook/instagram`.

If you prefer Postgres, add the Railway Postgres plugin, set `DATABASE_URL=${{Postgres.DATABASE_URL}}`, and remove the disk. Tables are created automatically on boot.

### Render

- A `render.yaml` blueprint is included. In Render: **New → Blueprint**, connect the repository, and set the **Blueprint Path** to `commentdm/render.yaml` (custom blueprint paths are supported).
- The blueprint provisions a Docker web service, a 1 GB disk at `/data`, and prompts for secrets (`sync: false`).
- Disks require a paid instance type. On the free plan, replace the disk/SQLite with a Render Postgres instance and set `DATABASE_URL` to its internal connection string.
- After the first deploy, set `PUBLIC_BASE_URL` to the Render URL and restart if needed.

### Docker anywhere

```bash
docker build -t commentdm .
docker run -d --name commentdm -p 8000:8000 \
  --env-file .env \
  -e DATABASE_URL=sqlite:////data/app.db \
  -e PUBLIC_BASE_URL=https://your-domain.example \
  -v commentdm-data:/data \
  commentdm
```

Check `docker logs commentdm`: the startup line prints which database file is in use, which is the quickest way to confirm the volume override took effect.

- One worker is recommended with SQLite (`uvicorn main:app` defaults to one).
- Multiple workers are supported for correctness because the unique `comment_id` constraint serializes dedupe, but SQLite write contention and in-process retries make a single worker simpler.
- Put a reverse proxy/load balancer in front and forward HTTPS. Uvicorn is started with `--proxy-headers`.
- Keep `/data` on a persistent volume; otherwise the database resets on redeploy.

### Health checks

`GET /health` returns `{"status": "ok"}` and is intentionally public, dependency-free, and excluded from Basic auth. Use it for Docker, Railway, Render, Kubernetes, etc.

---

## Security

- **Webhook signatures are mandatory.** Every POST is verified as `HMAC-SHA256(app_secret, raw_body)` against `X-Hub-Signature-256`, in constant time. Missing/invalid signatures get 403. If no app secret is configured, the webhook returns 503 unless you explicitly opt into unsigned mode.
- **Verify token** is used only for Meta's GET challenge and is never returned to the browser.
- **Secrets stay server-side.** The raw access token is never serialized in HTML or JSON. The UI shows a masked suffix. App secret, verify token, app ID and token source are surfaced only as booleans/status labels.
- **Token storage:** the token saved from Settings is stored **in plaintext** in the database (SQLite file or Postgres). Protect the volume/database with filesystem permissions, network isolation and encryption at rest; use a dedicated database user. The env fallback is only in process memory. Neither is encrypted by the application.
- **Dashboard auth:** set `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` in production. Without it, anyone who can reach the URL can edit campaigns and see the masked credential state. There is no per-user account system.
- **HTTPS everywhere:** the webhook must be HTTPS; use TLS at the proxy/platform.
- **CSRF / XSS:** the REST API accepts JSON only and uses Basic auth (not cookie sessions), so classic CSRF doesn't apply. Jinja autoescaping plus `textContent`-based JS rendering prevent injection; a strict CSP (`script-src 'self'`) blocks inline scripts. No third-party CDNs are used.
- **Log hygiene:** the client logs method, path, status, latency and Graph error codes; it never logs the access token. Response payloads are sanitized defensively. httpx's request logging is raised to WARNING so full URLs with `access_token` are not emitted at INFO.
- **Webhook replay:** an attacker with a valid old payload/signature can replay it; the unique comment ledger absorbs duplicates. Clearing Activity resets that protection.
- **Rate-limit handling** is best-effort and bounded; it does not infinitely retry.
- **No unofficial automation:** no Selenium, Playwright, instagrapi, browser-cookie hacks, or username/password login. Only Meta's official Graph API endpoints are called.

If you expose the app publicly, also consider an IP allowlist on `/webhook/instagram`, a WAF, and fail2ban for repeated 401s.

---

## Token refresh (60-day expiry)

Long-lived User tokens expire after ~60 days. There are two supported ways to refresh:

**Dashboard:** Settings → **Refresh token**. This calls `POST /api/config/refresh-token`, which exchanges the stored token via `GET /oauth/access_token?grant_type=fb_exchange_token` and saves the new token. It requires `INSTAGRAM_APP_ID` and `INSTAGRAM_APP_SECRET` (or `FACEBOOK_APP_SECRET`) to be configured. The new token is never displayed.

**CLI:**

```bash
cd commentdm
source .venv/bin/activate
python scripts/refresh_token.py
```

- Saves to the same database the app uses.
- Masks the token by default; use `--print-token` if you need to copy it to another host.
- `--no-save` leaves the DB untouched (useful for testing).

**Do not wait for expiry.** After the token expires, the refresh call fails and you must generate a new token in the Graph API Explorer. A monthly cron job or calendar reminder is the safest approach.

The app does not store the token's expiry date (Meta does not return it on normal requests), so it cannot display a countdown. Track the date when you generate the token.

---

## Database & moving to Postgres

Tables are created automatically at startup (`Base.metadata.create_all`). No Alembic migrations are included; for evolving production schemas, add Alembic or manage schema changes manually.

### SQLite

- Default URL: `sqlite:///./app.db` (relative to `commentdm/`).
- The app enables `foreign_keys`, `busy_timeout=30s`, and WAL mode.
- Good for one instance, low-to-moderate traffic, and demos.
- Back up the file (`app.db` plus `-wal`/`-shm`) or use a volume snapshot.

### Postgres

1. Provision Postgres (Railway/Render/Supabase/Neon/RDS).
2. Set `DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname` (the `postgres://` form from providers is normalized automatically).
3. Restart. The `psycopg` driver is already in `requirements.txt`.
4. Keep one worker or scale behind the shared DB; the unique constraint still protects dedupe.

### Tables

| Table | Key columns |
|---|---|
| `config` | single row (`id=1`): `access_token`, `page_id`, `instagram_business_account_id`, `instagram_username`, timestamps |
| `campaigns` | `name`, `post_id`, `keywords`, `comment_reply`, `dm_message`, `is_active`, cached post metadata, counters |
| `processed_comments` | unique `comment_id`, `campaign_id` (SET NULL on delete), commenter, matched keyword, statuses, `error_detail`, timestamps |

The processed-comment table intentionally doubles as the activity log.

---

## Testing

```bash
cd commentdm
pip install -r requirements-dev.txt
pytest -q
```

The suite (66 tests) uses a temporary SQLite database and a fake Instagram client; **no real Graph API calls or credentials are required**. It covers:

- health, dashboard rendering, security headers and redirect behavior;
- keyword parsing/matching (case, whitespace, partial, longest match, active filter);
- campaign/config CRUD, validation messages, token masking, token clearing;
- preview fetching and cache fallback;
- simulation/dry-run behavior and stats;
- webhook verification, signature enforcement, malformed JSON, ignored events, account filtering;
- end-to-end webhook processing with deduplication and activity logging;
- retry/backoff behavior and Graph error translation;
- Basic auth enforcement.

### Testing the webhook locally without Instagram

1. Set `FACEBOOK_APP_SECRET` and `WEBHOOK_VERIFY_TOKEN` in `.env`, start the app.
2. Create a campaign with any numeric post ID (use the exact post ID you want to test).
3. Send a signed fake comment:

```bash
python scripts/send_test_webhook.py \
  --post-id 17895695668004550 \
  --text "what is the price?" \
  --comment-id test-1
```

The receiver will accept and process it. If real credentials are configured, the app will attempt the public reply/DM using the fake comment ID; Instagram will reject it, and Activity will show a failure with Meta's error message. That is a useful test of error handling, not a delivery test. Reuse `--comment-id test-1` to confirm deduplication.

You can also exercise the exact same processing path without any API call via the campaign's **Test** button.

### Signature test with curl

```bash
BODY='{"object":"instagram","entry":[]}'
SECRET=$(grep '^FACEBOOK_APP_SECRET=' .env | cut -d= -f2-)
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -r | cut -d' ' -f1)"
curl -i -X POST http://localhost:8000/webhook/instagram \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: $SIG" \
  --data "$BODY"
```

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Meta says "The URL couldn't be validated" | The app is not reachable over HTTPS, `PUBLIC_BASE_URL`/callback URL is wrong, or `WEBHOOK_VERIFY_TOKEN` does not match exactly. Check the app logs; the GET handler returns the challenge only when the token matches. |
| Webhook POSTs return 403 | Missing/invalid `X-Hub-Signature-256`, wrong `FACEBOOK_APP_SECRET`, or a proxy modifying the body. Verify the raw body is forwarded unchanged (no request transformation). |
| Webhook POSTs return 503 | `FACEBOOK_APP_SECRET` is empty and unsigned mode is off. Set the secret. |
| 200 and `queued: 0` | Event is a reply-to-comment, authored by the business, from another account, or not a comment field. Also check the post ID matches exactly. |
| Comment matched but reply/DM failed | Check **Activity → Details** for the Meta error code. Common: expired token (190), missing permission (200/10), unsupported endpoint, media not found (100), rate limit (4/17/32/613), private reply already sent (2534014). |
| No DM arrives | DM must be a private reply within 7 days; one per comment; `instagram_manage_messages` must be approved; the recipient may see it in **Requests**; the commenter may have DMs restricted. |
| Standard DM fallback fails | The user has not messaged the business and there is no open 24-hour conversation. This is expected; the private reply is the supported path. |
| Webhooks work for testers only | The app is in Development mode; switch to Live and get Advanced Access. Add non-testers via App Review. |
| `instagram_manage_messages` not available | Some use cases require approval. Submit App Review with a screencast; see [DM rules](#read-this-first-instagram-dm-rules). |
| "Post ID must be numeric" | You pasted the URL/shortcode. Use the numeric media ID. |
| Post preview fails but the campaign saves | The token lacks `instagram_basic`, the post is not owned by the account, or the token expired. Campaigns are saved regardless; fix credentials and click Preview again. |
| Thumbnail URL broken in the dashboard | Instagram CDN URLs are time-limited. Click **Preview** to refresh; a new campaign save re-caches it. |
| Duplicate replies/DMs | The dedupe ledger was cleared, or Meta delivered events with different comment IDs. Check the unique `comment_id` rows. Do not delete Activity if you need strict dedupe. |
| `database is locked` (SQLite) | Multiple workers/instances writing concurrently. Run one worker, raise the volume IOPS, or migrate to Postgres. WAL + 30s busy timeout already help. |
| `graph.facebook.com` connection error | The container cannot reach Meta (egress firewall/DNS). Allow outbound HTTPS. In local sandboxes without internet the connection test will fail by design; use the simulation. |
| 401 on the dashboard | Basic auth is enabled. Use the configured username/password. |
| Token expired | Generate a new long-lived token in the Graph API Explorer; refresh before day 60 next time. |
| `ALLOW_UNSIGNED_WEBHOOKS` set in production | Remove it. It is a local-only escape hatch and is logged loudly. |

Useful logs:

```bash
# Docker
docker logs -f commentdm

# Railway/Render: use the dashboard logs
# Local
uvicorn main:app --log-level info
```

The app logs Instagram calls as `Graph POST /v23.0/… → 200 in 123ms`, plus sanitized error codes and fbtrace IDs. Tokens are not logged.

---

## Limitations & possible next steps

Deliberate scope choices:

- **One Instagram account per deployment.** Credentials are app-wide, not multi-tenant. Supporting agencies/multiple clients would require an account/tenant model and OAuth onboarding.
- **Manual credential entry.** There is no "Login with Facebook" OAuth flow; tokens are generated in the Graph API Explorer. This keeps the setup auditable and avoids storing OAuth client flows.
- **One private reply per comment**, per Meta's rules. No drip sequences, no broadcast DMs, no inbox UI.
- **In-process background tasks.** No durable queue, no automatic retry after a crash. Add Redis + RQ/Celery for production-grade at-least-once processing.
- **No scheduled retry of rate-limited failures.** They are logged as failed; re-comment or add a queue worker.
- **SQLite by default.** Single instance; use Postgres for horizontal scale.
- **Public replies to live video comments are unsupported by Meta.** The app still attempts the call, logs the failure, and may still send the DM.
- **No automatic webhook subscription verification.** The Settings button calls `subscribed_apps`, and Meta's dashboard shows delivery logs, but the app does not poll subscription status.
- **No media upload, caption generation, or AI copywriting.** This is a rules engine, not a content generator.
- **No user accounts/roles, audit of dashboard logins, or CSRF tokens** (Basic auth + JSON, no cookies).
- **Activity retention is unlimited until cleared.** Add a scheduled cleanup if the table grows.
- **Tests never call the real Graph API.** Live behavior depends on Meta's current error codes, permissions and review status.

Possible next steps: a durable worker queue, multiple accounts, an OAuth onboarding flow, a keyword autocomplete/picker, a media picker (instead of pasting IDs), per-campaign analytics, quiet hours, and scheduled token-rotation alerts.

---

## License / attribution

This is a private project template. Add a license file if you plan to distribute it. Built exclusively on Meta's official Instagram Graph API; Instagram and Meta are trademarks of Meta Platforms, Inc. This project is not affiliated with or endorsed by Meta or ManyChat.
