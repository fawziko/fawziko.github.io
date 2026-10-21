"""CommentDM — Instagram comment-to-DM automation.

Run locally:
    cd commentdm
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import BASE_DIR, get_settings
from database import engine, init_db
from routes import api as api_routes
from routes import dashboard as dashboard_routes
from routes import webhook as webhook_routes

logger = logging.getLogger("commentdm")


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    # httpx logs full request URLs at INFO; our client already logs safely.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    logger.info(
        "%s v%s starting | env=%s | graph=%s | db=%s",
        settings.app_name,
        settings.version,
        settings.environment,
        settings.graph_api_version,
        engine.dialect.name,
    )
    if not settings.facebook_app_secret:
        logger.warning(
            "FACEBOOK_APP_SECRET is not set — Instagram webhooks will be rejected "
            "until it is configured."
        )
    if not settings.webhook_verify_token:
        logger.warning("WEBHOOK_VERIFY_TOKEN is not set — Meta cannot verify the webhook.")
    if settings.allow_unsigned_webhooks:
        logger.warning(
            "ALLOW_UNSIGNED_WEBHOOKS=true — webhook signatures are NOT validated. "
            "This is insecure and should only be used for local development."
        )
    if settings.is_production and not settings.dashboard_auth_enabled:
        logger.warning(
            "DASHBOARD_USERNAME/DASHBOARD_PASSWORD are not set. The dashboard and "
            "credentials form are publicly reachable."
        )
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="CommentDM",
    description=(
        "Instagram comment-to-DM automation built on the official Instagram Graph API."
    ),
    version=get_settings().version,
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=800)

CSP = (
    "default-src 'self'; "
    "img-src 'self' data: https:; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault("Content-Security-Policy", CSP)
    # Never cache private dashboard/API responses.
    if request.url.path.startswith(("/dashboard", "/api")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Turn Pydantic errors into a single readable message for the UI."""
    errors = []
    first_message = "Please check the highlighted fields."
    for error in exc.errors():
        location = ".".join(
            str(part) for part in error.get("loc", ()) if part not in {"body", "query", "path"}
        )
        message = str(error.get("msg", "Invalid value")).replace("Value error, ", "")
        if not first_message or first_message.startswith("Please check"):
            first_message = f"{location}: {message}" if location else message
        errors.append({"loc": location, "msg": message, "type": error.get("type")})
    return JSONResponse(
        status_code=422,
        content={"detail": first_message, "errors": errors},
    )


app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

app.include_router(dashboard_routes.router)
app.include_router(webhook_routes.router)
app.include_router(api_routes.router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Deployment health check (kept public and dependency-free)."""
    return {"status": "ok"}


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
