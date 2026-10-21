from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPBasicCredentials

import security
from config import get_settings
from security import compute_signature, verify_signature


def test_signature_round_trip():
    body = b'{"object":"instagram"}'
    header = compute_signature("top-secret", body)
    assert header.startswith("sha256=")
    assert verify_signature("top-secret", body, header)
    assert not verify_signature("other-secret", body, header)
    assert not verify_signature("top-secret", body + b" ", header)
    assert not verify_signature("top-secret", body, None)


def test_signature_rejects_plain_hex_without_prefix():
    body = b"hello"
    assert not verify_signature("secret", body, "deadbeef")


def test_basic_auth_disabled_by_default():
    asyncio.run(security.require_dashboard_auth(None))  # does not raise


def test_basic_auth_enforced_when_configured(monkeypatch):
    settings = replace(
        get_settings(), dashboard_username="admin", dashboard_password="s3cret-pass"
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)

    with pytest.raises(HTTPException) as missing:
        asyncio.run(security.require_dashboard_auth(None))
    assert missing.value.status_code == 401

    bad = HTTPBasicCredentials(username="admin", password="wrong")
    with pytest.raises(HTTPException):
        asyncio.run(security.require_dashboard_auth(bad))

    good = HTTPBasicCredentials(username="admin", password="s3cret-pass")
    asyncio.run(security.require_dashboard_auth(good))


def test_api_requires_basic_auth_when_enabled(client, monkeypatch):
    settings = replace(
        get_settings(), dashboard_username="admin", dashboard_password="s3cret-pass"
    )
    monkeypatch.setattr(security, "get_settings", lambda: settings)

    assert client.get("/api/config").status_code == 401
    assert client.get("/api/config", auth=("admin", "wrong")).status_code == 401
    assert client.get("/api/config", auth=("admin", "s3cret-pass")).status_code == 200
