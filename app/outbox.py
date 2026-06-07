"""
Outbox engine — the single place that actually sends email, under the
business-hours window + daily cap (+ warm-up).

Order each run:
  1. due follow-ups (one per lead, reply/opt-out/bounce-safe)
  2. operator-approved initial emails
…stopping when the window closes or the daily cap is hit.

The caller (scripts/run_outbox.py) refreshes inbound replies FIRST so a lead
who just replied is never followed-up (reply-race fix).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Lead
from app.outreach_send import send_followup_now, send_initial_now
from app.sending import remaining_today, within_window

log = logging.getLogger(__name__)

_BLOCKED_DELIVERY = ("bounced", "dead")


def _due_followups(db: Session) -> list[Lead]:
    now = datetime.now(timezone.utc)
    return (
        db.query(Lead)
        .filter(
            Lead.outreach_status == "first_sent",
            Lead.reply_status == "none",
            Lead.opt_out == False,  # noqa: E712
            Lead.follow_up_due_at <= now,
            Lead.email.isnot(None),
            (Lead.delivery_status.is_(None)) | (Lead.delivery_status.notin_(_BLOCKED_DELIVERY)),
        )
        .all()
    )


def _approved_initials(db: Session) -> list[Lead]:
    return (
        db.query(Lead)
        .filter(
            Lead.outreach_status == "approved",
            Lead.opt_out == False,  # noqa: E712
            Lead.email.isnot(None),
            (Lead.delivery_status.is_(None)) | (Lead.delivery_status.notin_(_BLOCKED_DELIVERY)),
        )
        .order_by(Lead.updated_at.asc())
        .all()
    )


def run_outbox(db: Session) -> dict:
    summary = {"window_open": within_window(), "followups_sent": [], "initials_sent": [],
               "remaining_after": 0, "errors": []}
    if not within_window():
        summary["note"] = "outside business-hours window — nothing sent"
        return summary

    rem = remaining_today(db)
    if rem <= 0:
        summary["note"] = "daily cap reached — nothing sent"
        return summary

    # 1. Follow-ups
    for lead in _due_followups(db):
        if rem <= 0:
            break
        try:
            send_followup_now(db, lead)
            summary["followups_sent"].append(f"{lead.company_name} <{lead.email}>")
            rem -= 1
        except Exception as exc:
            db.rollback()
            summary["errors"].append(f"followup {lead.company_name}: {exc}")

    # 2. Approved initials
    for lead in _approved_initials(db):
        if rem <= 0:
            break
        try:
            send_initial_now(db, lead)
            summary["initials_sent"].append(f"{lead.company_name} <{lead.email}>")
            rem -= 1
        except Exception as exc:
            db.rollback()
            summary["errors"].append(f"initial {lead.company_name}: {exc}")

    summary["remaining_after"] = rem
    return summary
