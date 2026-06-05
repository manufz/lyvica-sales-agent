from __future__ import annotations
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Security, status
from sqlalchemy.orm import Session

from app.config import settings
from app.contact_discovery import discover_contacts
from app.db import get_db
from app.email_sender import send_email
from app.followups import get_due_leads, send_due_followups
from app.models import Lead, Message
from app.outreach_templates import (
    derive_desired_action,
    derive_primary_issue,
    render_initial,
)
from app.reply_classifier import classify_reply_text
from app.schemas import (
    ClassifyReplyRequest,
    ClassifyResult,
    DraftOut,
    FollowupSummary,
    IngestLeadRequest,
    LeadOut,
    ResearchRequest,
    SendEmailRequest,
    SendResult,
    StripeCheckoutRequest,
    StripeResult,
)
from app.scoring_client import score_domain
from app.stripe_client import get_or_create_checkout_link

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(title="Lyvica Sales Agent", version="0.1.0")


# ── Auth ──────────────────────────────────────────────────────────────────────

def require_hermes_secret(x_hermes_secret: Annotated[Optional[str], Header()] = None) -> None:
    if x_hermes_secret != settings.HERMES_SHARED_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing x-hermes-secret")


HermesAuth = Depends(require_hermes_secret)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True}


# ── Lead Research ─────────────────────────────────────────────────────────────

@app.post("/leads/research", response_model=LeadOut, dependencies=[HermesAuth])
def research_lead(req: ResearchRequest, db: Session = Depends(get_db)):
    from urllib.parse import urlparse

    parsed = urlparse(req.website_url)
    domain = parsed.netloc or parsed.path
    domain = domain.removeprefix("www.")

    # Contact discovery — never crash the whole flow
    try:
        contacts = discover_contacts(req.website_url)
    except Exception as exc:
        log.error("contact discovery failed: %s", exc)
        contacts = {
            "email_addresses": [], "email": None,
            "contact_form_url": None, "instagram_url": None, "checked_urls": [],
        }

    # Scoring — never crash the whole flow
    scoring = score_domain(
        domain=domain,
        company_name=req.company_name,
        city=req.city,
        industry=req.industry,
    )

    # Recommended channel
    if contacts["email"]:
        channel = "email"
    elif contacts["contact_form_url"]:
        channel = "contact_form"
    elif contacts["instagram_url"]:
        channel = "instagram"
    else:
        channel = "none"

    pitch_angles = scoring.get("pitch_angles") or []
    primary_issue = derive_primary_issue(pitch_angles)
    desired_action = derive_desired_action(req.industry)

    # Upsert lead by domain + company_name
    lead = db.query(Lead).filter_by(domain=domain, company_name=req.company_name).first()
    if not lead:
        lead = Lead(id=uuid.uuid4())
        db.add(lead)

    lead.company_name = req.company_name
    lead.website_url = req.website_url
    lead.domain = domain
    lead.city = req.city
    lead.country = req.country
    lead.industry = req.industry
    lead.email = contacts["email"]
    lead.email_addresses = contacts["email_addresses"]
    lead.contact_form_url = contacts["contact_form_url"]
    lead.instagram_url = contacts["instagram_url"]
    lead.score = scoring.get("score")
    lead.tier = scoring.get("tier")
    lead.confidence = scoring.get("confidence")
    lead.subscores = scoring.get("subscores")
    lead.pitch_angles = pitch_angles
    lead.scoring_payload = scoring.get("scoring_payload")
    lead.primary_issue = primary_issue
    lead.desired_action = desired_action
    lead.recommended_channel = channel
    lead.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(lead)
    return lead


# ── Draft Initial ─────────────────────────────────────────────────────────────

@app.post("/leads/{lead_id}/draft-initial", response_model=DraftOut, dependencies=[HermesAuth])
def draft_initial(lead_id: uuid.UUID, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")

    primary_issue = lead.primary_issue or derive_primary_issue(lead.pitch_angles or [])
    desired_action = lead.desired_action or derive_desired_action(lead.industry)

    subject, body = render_initial(
        company_name=lead.company_name,
        industry=lead.industry or "local",
        city=lead.city or "your area",
        primary_issue=primary_issue,
        desired_action=desired_action,
    )

    lead.first_subject = subject
    lead.first_body = body
    lead.primary_issue = primary_issue
    lead.desired_action = desired_action
    db.commit()

    return DraftOut(subject=subject, body=body)


# ── Send Initial ──────────────────────────────────────────────────────────────

@app.post("/leads/{lead_id}/send-initial", response_model=SendResult, dependencies=[HermesAuth])
def send_initial(lead_id: uuid.UUID, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not lead.email:
        raise HTTPException(400, "Lead has no email address")
    if not lead.first_body or not lead.first_subject:
        raise HTTPException(400, "Draft not yet generated — call /draft-initial first")
    if lead.opt_out:
        raise HTTPException(400, "Lead has opted out")

    result = send_email(lead.email, lead.first_subject, lead.first_body)

    now = datetime.now(timezone.utc)
    msg = Message(
        id=uuid.uuid4(),
        lead_id=lead.id,
        channel="email",
        direction="outbound",
        subject=lead.first_subject,
        body=lead.first_body,
        status="sent",
        provider_payload=result,
        sent_at=now,
    )
    db.add(msg)

    lead.outreach_status = "first_sent"
    lead.first_sent_at = now
    lead.follow_up_due_at = now + timedelta(days=3)
    db.commit()

    return SendResult(status="sent", message_id=msg.id, provider_id=result.get("id"))


# ── Raw Email Send ────────────────────────────────────────────────────────────

@app.post("/email/send", response_model=SendResult, dependencies=[HermesAuth])
def send_raw_email(req: SendEmailRequest, db: Session = Depends(get_db)):
    result = send_email(req.to, req.subject, req.body)

    msg = Message(
        id=uuid.uuid4(),
        lead_id=req.lead_id,
        channel="email",
        direction="outbound",
        subject=req.subject,
        body=req.body,
        status="sent",
        provider_payload=result,
        sent_at=datetime.now(timezone.utc),
    )
    if req.lead_id:
        lead = db.get(Lead, req.lead_id)
        if not lead:
            raise HTTPException(404, "Lead not found")
    db.add(msg)
    db.commit()

    return SendResult(status="sent", message_id=msg.id, provider_id=result.get("id"))


# ── Follow-ups ────────────────────────────────────────────────────────────────

@app.get("/followups/due", response_model=list[LeadOut])
def list_due_followups(db: Session = Depends(get_db)):
    return get_due_leads(db)


@app.post("/followups/send-due", response_model=FollowupSummary, dependencies=[HermesAuth])
def trigger_send_due(db: Session = Depends(get_db)):
    return send_due_followups(db)


# ── Reply Classifier ──────────────────────────────────────────────────────────

@app.post("/replies/classify", response_model=ClassifyResult, dependencies=[HermesAuth])
def classify_reply(req: ClassifyReplyRequest, db: Session = Depends(get_db)):
    lead = db.get(Lead, req.lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")

    classification, action = classify_reply_text(req.body)

    lead.reply_status = classification
    if classification in ("not_interested", "unsubscribe"):
        lead.opt_out = True

    msg = Message(
        id=uuid.uuid4(),
        lead_id=lead.id,
        channel="email",
        direction="inbound",
        subject=None,
        body=req.body,
        status="received",
        provider_payload={"from_email": req.from_email},
        sent_at=datetime.now(timezone.utc),
    )
    db.add(msg)
    db.commit()

    return ClassifyResult(
        classification=classification,
        recommended_next_action=action,
        lead_id=lead.id,
    )


# ── Stripe ────────────────────────────────────────────────────────────────────

@app.post("/stripe/checkout-link", response_model=StripeResult, dependencies=[HermesAuth])
def checkout_link(req: StripeCheckoutRequest, db: Session = Depends(get_db)):
    if not req.buying_intent:
        raise HTTPException(400, "buying_intent must be true to create a payment link")

    lead = db.get(Lead, req.lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")

    link = get_or_create_checkout_link(req.package)
    lead.stripe_link = link
    db.commit()

    return StripeResult(link=link, lead_id=lead.id, package=req.package)


# ── Lead Ingest ───────────────────────────────────────────────────────────────

@app.post("/leads/ingest", dependencies=[HermesAuth])
def ingest_leads(leads: list[IngestLeadRequest], db: Session = Depends(get_db)):
    from urllib.parse import urlparse

    created = 0
    updated = 0
    for item in leads:
        domain = None
        if item.website_url:
            p = urlparse(item.website_url)
            domain = (p.netloc or p.path).removeprefix("www.")

        lead = None
        if domain:
            lead = db.query(Lead).filter_by(domain=domain, company_name=item.company_name).first()

        if lead:
            updated += 1
        else:
            lead = Lead(id=uuid.uuid4())
            db.add(lead)
            created += 1

        lead.company_name = item.company_name
        lead.website_url = item.website_url
        lead.domain = domain
        lead.city = item.city
        lead.country = item.country
        lead.industry = item.industry
        lead.updated_at = datetime.now(timezone.utc)

    db.commit()
    return {"created": created, "updated": updated}
