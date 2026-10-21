"""Test configuration.

Environment is configured *before* the app modules import so the settings
singleton and the SQLAlchemy engine point at the test database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

TEST_DB = APP_DIR / "test_app.db"
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{TEST_DB}",
        "FACEBOOK_APP_SECRET": "test-app-secret",
        "WEBHOOK_VERIFY_TOKEN": "test-verify-token",
        "ALLOW_UNSIGNED_WEBHOOKS": "false",
        "APP_ENV": "test",
        "LOG_LEVEL": "WARNING",
        "PUBLIC_BASE_URL": "https://example.test",
    }
)
for _name in (
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_BUSINESS_ACCOUNT_ID",
    "INSTAGRAM_APP_ID",
    "INSTAGRAM_APP_SECRET",
    "DASHBOARD_USERNAME",
    "DASHBOARD_PASSWORD",
):
    os.environ.pop(_name, None)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_database(client):
    from database import Base, engine
    import models  # noqa: F401 — register mappers

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
