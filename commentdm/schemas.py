"""Pydantic request models (validation happens here, never in templates)."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from keywords import MAX_KEYWORD_LENGTH, MAX_KEYWORDS, normalize_keywords, split_keywords

_MEDIA_ID_RE = re.compile(r"^\d{5,30}$")
_IG_ID_RE = re.compile(r"^\d{5,30}$")


class CampaignPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    post_id: str = Field(..., min_length=5, max_length=30)
    keywords: str = Field(..., min_length=1, max_length=1200)
    comment_reply: str = Field(..., min_length=1, max_length=2200)
    dm_message: str = Field(..., min_length=1, max_length=1000)
    is_active: bool = True

    @field_validator("post_id")
    @classmethod
    def _validate_post_id(cls, value: str) -> str:
        value = value.strip()
        if not _MEDIA_ID_RE.match(value):
            raise ValueError(
                "Post ID must be the numeric Instagram media ID (e.g. 17895695668004550)."
            )
        return value

    @field_validator("keywords")
    @classmethod
    def _validate_keywords(cls, value: str) -> str:
        normalized = normalize_keywords(value)
        items = split_keywords(normalized)
        if not items:
            raise ValueError("Add at least one trigger keyword.")
        if len(items) > MAX_KEYWORDS:
            raise ValueError(f"Use at most {MAX_KEYWORDS} keywords per campaign.")
        for keyword in items:
            if len(keyword) > MAX_KEYWORD_LENGTH:
                raise ValueError(
                    f"The keyword “{keyword[:30]}…” is too long "
                    f"(max {MAX_KEYWORD_LENGTH} characters)."
                )
        return normalized

    @field_validator("comment_reply", "dm_message")
    @classmethod
    def _validate_copy(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message text cannot be empty.")
        return value.strip()


class ConfigPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    access_token: str | None = Field(default=None, max_length=4096)
    page_id: str | None = Field(default=None, max_length=80)
    instagram_business_account_id: str | None = Field(default=None, max_length=80)
    clear_access_token: bool = False

    @field_validator("access_token")
    @classmethod
    def _token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        # A masked placeholder or blank field never overwrites the stored token.
        if not value or value.startswith("•") or value == "__stored__":
            return None
        return value

    @field_validator("page_id", "instagram_business_account_id")
    @classmethod
    def _ids(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value == "":
            return ""
        if not _IG_ID_RE.match(value):
            raise ValueError("This ID must be numeric (copy it from the Graph API Explorer).")
        return value


class PostPreviewPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    post_id: str = Field(..., min_length=5, max_length=30)

    @field_validator("post_id")
    @classmethod
    def _post_id(cls, value: str) -> str:
        value = value.strip()
        if not _MEDIA_ID_RE.match(value):
            raise ValueError(
                "Post ID must be the numeric Instagram media ID (e.g. 17895695668004550)."
            )
        return value


class SimulatePayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    comment_text: str = Field(..., min_length=1, max_length=2200)
    commenter_username: str | None = Field(default=None, max_length=60)

    @field_validator("comment_text")
    @classmethod
    def _comment(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Write a test comment first.")
        return value

    @field_validator("commenter_username")
    @classmethod
    def _username(cls, value: str | None) -> str | None:
        if not value:
            return None
        return re.sub(r"[^A-Za-z0-9._]", "", value.strip().lstrip("@")) or None
