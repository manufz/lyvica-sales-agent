from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.types import JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Identity
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    website_url: Mapped[Optional[str]] = mapped_column(Text)
    domain: Mapped[Optional[str]] = mapped_column(Text)
    city: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(Text)
    industry: Mapped[Optional[str]] = mapped_column(Text)

    # Contact
    email: Mapped[Optional[str]] = mapped_column(Text)
    email_addresses: Mapped[Optional[list]] = mapped_column(JSON)
    contact_form_url: Mapped[Optional[str]] = mapped_column(Text)
    instagram_url: Mapped[Optional[str]] = mapped_column(Text)
    phone: Mapped[Optional[str]] = mapped_column(Text)

    # Scoring
    score: Mapped[Optional[float]] = mapped_column(Numeric)
    tier: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric)
    subscores: Mapped[Optional[dict]] = mapped_column(JSON)
    pitch_angles: Mapped[Optional[list]] = mapped_column(JSON)
    buying_signals: Mapped[Optional[list]] = mapped_column(JSON)
    diy_builder: Mapped[Optional[str]] = mapped_column(Text)
    scoring_payload: Mapped[Optional[dict]] = mapped_column(JSON)

    # Outreach
    primary_issue: Mapped[Optional[str]] = mapped_column(Text)
    desired_action: Mapped[Optional[str]] = mapped_column(Text)
    recommended_channel: Mapped[Optional[str]] = mapped_column(Text)
    outreach_status: Mapped[str] = mapped_column(Text, default="new")
    first_subject: Mapped[Optional[str]] = mapped_column(Text)
    first_body: Mapped[Optional[str]] = mapped_column(Text)
    first_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    follow_up_subject: Mapped[Optional[str]] = mapped_column(Text)
    follow_up_body: Mapped[Optional[str]] = mapped_column(Text)
    follow_up_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    follow_up_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reply_status: Mapped[str] = mapped_column(Text, default="none")
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_link: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    messages: Mapped[list[Message]] = relationship("Message", back_populates="lead")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id"), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    lead: Mapped[Lead] = relationship("Lead", back_populates="messages")


class MarketCoverage(Base):
    """Tracks how thoroughly each (city, sector) market has been worked,
    so the selector can rotate intelligently and by yield."""
    __tablename__ = "market_coverage"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str] = mapped_column(Text, nullable=False)
    total_sourced: Mapped[int] = mapped_column(default=0)
    total_qualified: Mapped[int] = mapped_column(default=0)
    runs: Mapped[int] = mapped_column(default=0)
    exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
