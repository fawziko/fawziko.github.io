"""Database models.

Three tables:
  * ``config``             — Instagram credentials saved from the dashboard.
  * ``campaigns``          — post + keywords + reply/DM copy.
  * ``processed_comments`` — dedupe ledger AND human-readable activity log.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from utils import utcnow


class Config(Base):
    """Single-row credential store (id is always 1)."""

    __tablename__ = "config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    instagram_business_account_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    instagram_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    post_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    keywords: Mapped[str] = mapped_column(Text, default="", nullable=False)  # comma-separated
    comment_reply: Mapped[str] = mapped_column(Text, default="", nullable=False)
    dm_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Cached post metadata, refreshed whenever the post ID is previewed.
    post_thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_permalink: Mapped[str | None] = mapped_column(Text, nullable=True)

    times_triggered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    processed_comments: Mapped[list["ProcessedComment"]] = relationship(
        back_populates="campaign", passive_deletes=True
    )


class ProcessedComment(Base):
    __tablename__ = "processed_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    comment_id: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    post_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    commenter_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commenter_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    comment_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    matched_keyword: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # processing | success | partial | failed | simulated
    status: Mapped[str] = mapped_column(String(20), default="processing", nullable=False, index=True)
    comment_reply_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    dm_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reply_comment_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    dm_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    campaign: Mapped[Campaign | None] = relationship(back_populates="processed_comments")


# Composite index for the dashboard's activity feed.
Index("ix_processed_comments_created_status", ProcessedComment.created_at, ProcessedComment.status)
