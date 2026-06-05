from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.email_sender import send_email
from app.models import Lead, Message
from app.outreach_templates import derive_desired_action, derive_primary_issue, render_followup
from app.schemas import FollowupSummary

log = logging.getLogger(__name__)


def get_due_leads(db: Session) -> list[Lead]:
    now = datetime.now(timezone.utc)
    return (
        db.query(Lead)
        .filter(
            Lead.outreach_status == "first_sent",
            Lead.reply_status == "none",
            Lead.opt_out == False,  # noqa: E712
            Lead.follow_up_due_at <= now,
        )
        .all()
    )


def send_due_followups(db: Session) -> FollowupSummary:
    leads = get_due_leads(db)
    sent = 0
    skipped = 0
    errors: list[str] = []

    for lead in leads:
        if lead.opt_out or lead.reply_status != "none":
            skipped += 1
            continue
        if not lead.email:
            log.info("lead %s has no email, skipping follow-up", lead.id)
            skipped += 1
            continue

        try:
            primary_issue = lead.primary_issue or derive_primary_issue(lead.pitch_angles or [])
            desired_action = lead.desired_action or derive_desired_action(lead.industry)
            first_subject = lead.first_subject or "your website"

            subject, body = render_followup(
                company_name=lead.company_name,
                first_subject=first_subject,
                primary_issue=primary_issue,
                desired_action=desired_action,
            )

            # Store drafts on lead for reference
            lead.follow_up_subject = subject
            lead.follow_up_body = body

            result = send_email(lead.email, subject, body)

            now = datetime.now(timezone.utc)
            msg = Message(
                id=uuid.uuid4(),
                lead_id=lead.id,
                channel="email",
                direction="outbound",
                subject=subject,
                body=body,
                status="sent",
                provider_payload=result,
                sent_at=now,
            )
            db.add(msg)

            lead.outreach_status = "follow_up_sent"
            lead.follow_up_sent_at = now
            db.commit()
            sent += 1
            log.info("follow-up sent to lead %s (%s)", lead.id, lead.email)

        except Exception as exc:
            db.rollback()
            msg = f"lead {lead.id}: {exc}"
            log.error("follow-up failed: %s", msg)
            errors.append(msg)

    return FollowupSummary(
        processed=len(leads),
        sent=sent,
        skipped=skipped,
        errors=errors,
    )
