from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


# ── Requests ──────────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    company_name: str
    website_url: str
    city: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    lead_id: Optional[uuid.UUID] = None


class ClassifyReplyRequest(BaseModel):
    lead_id: uuid.UUID
    from_email: str
    body: str


class StripeCheckoutRequest(BaseModel):
    lead_id: uuid.UUID
    package: str  # "starter" | "pro"
    buying_intent: bool


class IngestLeadRequest(BaseModel):
    company_name: str
    website_url: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None


# ── Responses ─────────────────────────────────────────────────────────────────

class ContactDiscovery(BaseModel):
    email_addresses: List[str]
    email: Optional[str]
    contact_form_url: Optional[str]
    instagram_url: Optional[str]
    checked_urls: List[str]


class LeadOut(BaseModel):
    id: uuid.UUID
    company_name: str
    website_url: Optional[str]
    domain: Optional[str]
    city: Optional[str]
    country: Optional[str]
    industry: Optional[str]
    email: Optional[str]
    email_addresses: Optional[List[str]]
    contact_form_url: Optional[str]
    instagram_url: Optional[str]
    phone: Optional[str]
    score: Optional[float]
    tier: Optional[str]
    confidence: Optional[float]
    pitch_angles: Optional[list]
    primary_issue: Optional[str]
    desired_action: Optional[str]
    recommended_channel: Optional[str]
    outreach_status: str
    first_subject: Optional[str]
    first_body: Optional[str]
    first_sent_at: Optional[datetime]
    follow_up_due_at: Optional[datetime]
    follow_up_sent_at: Optional[datetime]
    reply_status: str
    opt_out: bool
    stripe_link: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DraftOut(BaseModel):
    subject: str
    body: str


class SendResult(BaseModel):
    status: str
    message_id: Optional[uuid.UUID] = None
    provider_id: Optional[str] = None


class FollowupSummary(BaseModel):
    processed: int
    sent: int
    skipped: int
    errors: List[str]


class ClassifyResult(BaseModel):
    classification: str
    recommended_next_action: str
    lead_id: uuid.UUID


class StripeResult(BaseModel):
    link: str
    lead_id: uuid.UUID
    package: str


class PipelineRequest(BaseModel):
    city: Optional[str] = None          # defaults to PIPELINE_DEFAULT_CITY
    industry: Optional[str] = None      # defaults to PIPELINE_DEFAULT_INDUSTRY
    country: Optional[str] = None
    limit: Optional[int] = None         # defaults to PIPELINE_DEFAULT_LIMIT
    min_score: Optional[float] = None   # defaults to PIPELINE_MIN_SCORE
    notify_telegram: bool = True


class PipelineResult(BaseModel):
    city: str
    industry: str
    total_sourced: int
    total_researched: int
    qualifying: int
    skipped_no_contact: int
    skipped_low_score: int
    leads: List[LeadOut]
    telegram_sent: bool
