"""
The actual send operations (initial + follow-up). Callers (the outbox) are
responsible for checking can_send_now() and opt-out/delivery state first.
Drafts are LLM-written on demand if missing.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.email_sender import send_email
from app.models import Lead, Message
from app.outreach_writer import write_followup, write_initial

log = logging.getLogger(__name__)


def send_initial_now(db: Session, lead: Lead) -> dict:
    """Send the first outreach email to a lead. Generates the draft if missing."""
    if not lead.first_subject or not lead.first_body:
        subject, body = write_initial(lead)
        lead.first_subject, lead.first_body = subject, body

    result = send_email(lead.email, lead.first_subject, lead.first_body)
    now = datetime.now(timezone.utc)
    db.add(Message(
        id=uuid.uuid4(), lead_id=lead.id, channel="email", direction="outbound",
        subject=lead.first_subject, body=lead.first_body, status="sent",
        provider_payload=result, sent_at=now,
    ))
    lead.outreach_status = "first_sent"
    lead.first_sent_at = now
    lead.follow_up_due_at = now + timedelta(days=3)
    db.commit()
    log.info("initial sent to %s (%s)", lead.email, lead.company_name)
    return result


def send_followup_now(db: Session, lead: Lead) -> dict:
    """Send the single follow-up to a lead."""
    subject, body = write_followup(lead)
    lead.follow_up_subject, lead.follow_up_body = subject, body

    result = send_email(lead.email, subject, body)
    now = datetime.now(timezone.utc)
    db.add(Message(
        id=uuid.uuid4(), lead_id=lead.id, channel="email", direction="outbound",
        subject=subject, body=body, status="sent",
        provider_payload=result, sent_at=now,
    ))
    lead.outreach_status = "follow_up_sent"
    lead.follow_up_sent_at = now
    db.commit()
    log.info("follow-up sent to %s (%s)", lead.email, lead.company_name)
    return result
