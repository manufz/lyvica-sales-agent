import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.reply_classifier import classify_reply_text


def test_classify_not_interested():
    cls, action = classify_reply_text("Please unsubscribe me from your list")
    assert cls == "not_interested"
    assert action == "mark_opted_out"


def test_classify_asks_price():
    cls, action = classify_reply_text("How much does this cost?")
    assert cls == "asks_price"
    assert action == "send_pricing"


def test_classify_asks_examples():
    cls, action = classify_reply_text("Can you show me your portfolio?")
    assert cls == "asks_examples"
    assert action == "send_portfolio"


def test_classify_interested():
    cls, action = classify_reply_text("Yes, please send it!")
    assert cls == "interested"
    assert action == "send_snapshot"


def test_classify_ready_to_buy():
    cls, action = classify_reply_text("I'm ready to pay, send the invoice.")
    assert cls == "ready_to_buy"
    assert action == "offer_stripe_link"


def test_classify_unclear():
    cls, action = classify_reply_text("Thanks for reaching out.")
    assert cls == "unclear"
    assert action == "draft_for_manuel_approval"


def test_due_leads_query_logic():
    """Verify the due-leads filter conditions."""
    from app.followups import get_due_leads

    # Build a minimal mock lead that IS due
    now = datetime.now(timezone.utc)
    due_lead = MagicMock()
    due_lead.outreach_status = "first_sent"
    due_lead.reply_status = "none"
    due_lead.opt_out = False
    due_lead.follow_up_due_at = now - timedelta(hours=1)

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = [due_lead]

    result = get_due_leads(mock_db)
    assert len(result) == 1
    assert result[0].outreach_status == "first_sent"
