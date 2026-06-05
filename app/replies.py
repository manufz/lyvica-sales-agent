"""
Inbound reply processing — shared logic for classifying a received email,
matching it to a lead, updating the lead, and storing the inbound message.
Used by the polling job (scripts/check_replies.py).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Lead, Message
from app.reply_classifier import classify_reply_text

log = logging.getLogger(__name__)


def process_inbound(db: Session, from_email: str, subject: Optional[str],
                    body: str, message_id: Optional[str] = None) -> dict:
    """
    Classify an inbound reply, match it to a lead by sender address, update the
    lead's reply_status (and opt_out), and store an inbound Message.
    Returns {classification, action, lead}.
    """
    from_addr = (from_email or "").lower().strip()
    classification, action = classify_reply_text(body or "")

    lead = None
    if from_addr:
        lead = db.query(Lead).filter(Lead.email.ilike(from_addr)).first()

    if lead:
        lead.reply_status = classification
        if classification in ("not_interested", "unsubscribe"):
            lead.opt_out = True
        db.add(Message(
            id=uuid.uuid4(), lead_id=lead.id, channel="email", direction="inbound",
            subject=subject, body=body or "", status="received",
            provider_payload={"from": from_addr, "message_id": message_id},
            sent_at=datetime.now(timezone.utc),
        ))
        db.commit()

    return {"classification": classification, "action": action, "lead": lead}
