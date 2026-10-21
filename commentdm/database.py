"""SQLAlchemy engine, session factory and declarative base.

SQLite is the default so the app runs with zero infrastructure. Set
``DATABASE_URL`` to a Postgres URL in production (the adapter is included in
``requirements.txt``).
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config import BASE_DIR, get_settings

logger = logging.getLogger(__name__)


def _prepare_url(url: str) -> str:
    """Normalise provider URLs and anchor relative SQLite paths to the app."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]

    if url.startswith("sqlite"):
        parsed = make_url(url)
        database = parsed.database
        if database and database != ":memory:" and not Path(database).is_absolute():
            # Relative to the application directory, not the process CWD. This
            # keeps the same database file no matter where uvicorn is started.
            absolute = (BASE_DIR / database).resolve()
            absolute.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{absolute}"
    return url


def _build_engine() -> Engine:
    settings = get_settings()
    url = _prepare_url(settings.database_url)
    kwargs: dict = {"pool_pre_ping": True, "future": True}

    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url or url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
        logger.info("Using SQLite database: %s", url.removeprefix("sqlite:///"))
    else:
        logger.info("Using SQL database: %s", make_url(url).render_as_string(hide_password=True))

    engine = create_engine(url, **kwargs)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables on boot. Lightweight and idempotent (no Alembic needed)."""
    import models  # noqa: F401  (registers mappers before create_all)

    Base.metadata.create_all(bind=engine)
