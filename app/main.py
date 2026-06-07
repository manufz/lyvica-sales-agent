from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Security, status
from sqlalchemy.orm import Session

from app.config import settings
from app.contact_discovery import discover_contacts
from app.db import get_db
from app.email_sender import send_email
from app.followups import get_due_leads, send_due_followups
from app.models import Lead, Message
from app.markets import get_coverage_stats, record_run, select_next_market, select_next_markets
from app.sourcer import source_leads
from app.outreach_templates import (
    derive_desired_action,
    derive_primary_issue,
)
from app.outreach_writer import rewrite, write_initial
from app.reply_classifier import classify_reply_text
from app.schemas import (
    ClassifyReplyRequest,
    ClassifyResult,
    DraftOut,
    EditRequest,
    FollowupSummary,
    IngestLeadRequest,
    LeadOut,
    MarketResult,
    PipelineRequest,
    PipelineResult,
    ResearchRequest,
    SweepRequest,
    SweepResult,
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
        website_url=req.website_url,
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
    lead.buying_signals = scoring.get("buying_signals") or []
    lead.diy_builder = scoring.get("diy_builder")
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
    """Generate (or regenerate) the LLM-written first-email draft for preview."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")

    subject, body = write_initial(lead)
    lead.first_subject = subject
    lead.first_body = body
    if lead.outreach_status == "new":
        lead.outreach_status = "drafted"
    db.commit()
    return DraftOut(subject=subject, body=body)


@app.post("/leads/{lead_id}/edit", response_model=DraftOut, dependencies=[HermesAuth])
def edit_draft(lead_id: uuid.UUID, req: EditRequest, db: Session = Depends(get_db)):
    """Revise the draft per an operator instruction (the `edit` command)."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not lead.first_body:
        # No draft yet → make one first, then apply the instruction.
        s, b = write_initial(lead)
        lead.first_subject, lead.first_body = s, b
    subject, body = rewrite(lead, req.instruction)
    lead.first_subject = subject
    lead.first_body = body
    db.commit()
    return DraftOut(subject=subject, body=body)


# ── Approve / queue for sending (model B: human-gated) ─────────────────────────

@app.post("/leads/{lead_id}/approve", dependencies=[HermesAuth])
def approve_lead(lead_id: uuid.UUID, db: Session = Depends(get_db)):
    """Queue a lead's initial email. The outbox sends it within business hours,
    under the daily cap. Generates the draft now if missing."""
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    if not lead.email:
        raise HTTPException(400, "Lead has no email address — cannot email")
    if lead.opt_out:
        raise HTTPException(400, "Lead has opted out")
    if lead.delivery_status in ("bounced", "dead"):
        raise HTTPException(400, f"Lead is {lead.delivery_status} — cannot email")

    if not lead.first_subject or not lead.first_body:
        lead.first_subject, lead.first_body = write_initial(lead)
    lead.outreach_status = "approved"
    db.commit()
    return {"status": "queued", "lead_id": str(lead.id),
            "company": lead.company_name, "email": lead.email}


@app.post("/leads/approve-pending", dependencies=[HermesAuth])
def approve_pending(db: Session = Depends(get_db)):
    """Approve every reviewed-but-unactioned lead with a usable email
    (the `send all` command). The daily cap still throttles actual sends."""
    pending = db.query(Lead).filter(
        Lead.outreach_status.in_(["new", "drafted"]),
        Lead.email.isnot(None),
        Lead.opt_out == False,  # noqa: E712
        (Lead.delivery_status.is_(None)) | (Lead.delivery_status.notin_(["bounced", "dead"])),
    ).all()
    for lead in pending:
        if not lead.first_subject or not lead.first_body:
            lead.first_subject, lead.first_body = write_initial(lead)
        lead.outreach_status = "approved"
    db.commit()
    return {"approved": len(pending)}


@app.post("/leads/{lead_id}/skip", dependencies=[HermesAuth])
def skip_lead(lead_id: uuid.UUID, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.outreach_status = "skipped"
    db.commit()
    return {"status": "skipped", "lead_id": str(lead.id)}


# ── Raw Email Send ────────────────────────────────────────────────────────────

@app.post("/email/send", response_model=SendResult, dependencies=[HermesAuth])
def send_raw_email(req: SendEmailRequest, db: Session = Depends(get_db)):
    # Validate the lead first (if one was given) before sending.
    if req.lead_id:
        lead = db.get(Lead, req.lead_id)
        if not lead:
            raise HTTPException(404, "Lead not found")

    result = send_email(req.to, req.subject, req.body)

    # Only store a Message when it's tied to a lead (messages.lead_id is required).
    msg_id = None
    if req.lead_id:
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
        db.add(msg)
        db.commit()
        msg_id = msg.id

    return SendResult(status="sent", message_id=msg_id, provider_id=result.get("id") or result.get("message_id"))


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


# Inbound replies are polled every 2h by scripts/check_replies.py (no webhook).


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


# ── Autonomous Pipeline ───────────────────────────────────────────────────────

def process_market(db: Session, city: str, industry: str,
                   country: Optional[str], limit: int, min_score: float) -> dict:
    """
    Work ONE (city, sector) market: source fresh businesses, discover contacts,
    score, draft outreach for qualifiers, and record coverage. Returns a dict
    with the qualifying Lead rows and the run stats. Shared by /leads/pipeline
    and /leads/sweep.
    """
    from urllib.parse import urlparse

    # Dedup: skip businesses already in the DB so each run finds FRESH leads.
    known_domains = {d for (d,) in db.query(Lead.domain).filter(Lead.domain.isnot(None)).all()}

    src = source_leads(
        city=city, industry=industry, country=country,
        limit=limit, exclude_domains=known_domains,
    )
    sourced = src["leads"]
    total_sourced = len(sourced)

    qualifying_leads: list[Lead] = []
    skipped_no_contact = 0
    skipped_low_score = 0

    for item in sourced:
        # Contact discovery — never crash the whole run
        try:
            contacts = discover_contacts(item["website_url"])
        except Exception as exc:
            log.error("contact discovery failed for %s: %s", item["website_url"], exc)
            contacts = {"email_addresses": [], "email": None,
                        "contact_form_url": None, "instagram_url": None, "checked_urls": []}

        if not (contacts["email"] or contacts["contact_form_url"] or contacts["instagram_url"]):
            skipped_no_contact += 1
            continue

        parsed = urlparse(item["website_url"])
        domain = (parsed.netloc or parsed.path).removeprefix("www.")
        scoring = score_domain(
            domain=domain, company_name=item["company_name"],
            city=city, industry=industry, website_url=item["website_url"],
        )

        score = scoring.get("score")
        buying_signals = scoring.get("buying_signals") or []
        if not scoring.get("scoreable", True):
            skipped_low_score += 1
            continue
        if score is not None and score < min_score and not buying_signals:
            skipped_low_score += 1
            continue

        if contacts["email"]:
            channel = "email"
        elif contacts["contact_form_url"]:
            channel = "contact_form"
        elif contacts["instagram_url"]:
            channel = "instagram"
        else:
            channel = "none"

        pitch_angles = scoring.get("pitch_angles") or []
        visible = scoring.get("visible_problems") or []
        primary_issue = visible[0] if visible else derive_primary_issue(pitch_angles)
        desired_action = derive_desired_action(industry)

        lead = db.query(Lead).filter_by(domain=domain, company_name=item["company_name"]).first()
        if not lead:
            lead = Lead(id=uuid.uuid4())
            db.add(lead)

        lead.company_name = item["company_name"]
        lead.website_url = item["website_url"]
        lead.domain = domain
        lead.city = city
        lead.country = country
        lead.industry = industry
        lead.email = contacts["email"]
        lead.email_addresses = contacts["email_addresses"]
        lead.contact_form_url = contacts["contact_form_url"]
        lead.instagram_url = contacts["instagram_url"]
        lead.score = scoring.get("score")
        lead.tier = scoring.get("tier")
        lead.confidence = scoring.get("confidence")
        lead.subscores = scoring.get("subscores")
        lead.pitch_angles = pitch_angles
        lead.buying_signals = buying_signals
        lead.diy_builder = scoring.get("diy_builder")
        lead.scoring_payload = scoring.get("scoring_payload")
        lead.primary_issue = primary_issue
        lead.desired_action = desired_action
        lead.recommended_channel = channel
        lead.updated_at = datetime.now(timezone.utc)
        # No draft here — the real email is LLM-written on preview/approve, so we
        # never accidentally send a stale template. Lead stays outreach_status="new".

        db.commit()
        db.refresh(lead)
        qualifying_leads.append(lead)

    record_run(db, city=city, sector=industry, sourced=total_sourced,
               qualified=len(qualifying_leads), exhausted=src["exhausted"])

    return {
        "city": city, "industry": industry,
        "total_sourced": total_sourced,
        "qualifying_leads": qualifying_leads,
        "skipped_no_contact": skipped_no_contact,
        "skipped_low_score": skipped_low_score,
    }


@app.post("/leads/pipeline", response_model=PipelineResult, dependencies=[HermesAuth])
def run_pipeline(req: PipelineRequest, db: Session = Depends(get_db)):
    """Work one market (selector picks it if city/industry omitted)."""
    if req.city and req.industry:
        city, industry = req.city, req.industry
    else:
        city, industry = select_next_market(db)
    limit = req.limit or settings.PIPELINE_DEFAULT_LIMIT
    min_score = req.min_score if req.min_score is not None else settings.PIPELINE_MIN_SCORE

    r = process_market(db, city, industry, req.country, limit, min_score)
    return PipelineResult(
        city=r["city"], industry=r["industry"],
        total_sourced=r["total_sourced"],
        total_researched=len(r["qualifying_leads"]),
        qualifying=len(r["qualifying_leads"]),
        skipped_no_contact=r["skipped_no_contact"],
        skipped_low_score=r["skipped_low_score"],
        leads=r["qualifying_leads"],
    )


@app.post("/leads/sweep", response_model=SweepResult, dependencies=[HermesAuth])
def run_sweep(req: SweepRequest, db: Session = Depends(get_db)):
    """
    Work several markets in one sweep, spread across different cities, so each
    run surfaces qualifying leads from multiple areas. Used by the twice-daily
    schedule and by Hermes when asked to prospect broadly.
    """
    count = req.count or 3
    limit = req.limit or settings.PIPELINE_DEFAULT_LIMIT
    min_score = req.min_score if req.min_score is not None else settings.PIPELINE_MIN_SCORE

    markets = select_next_markets(db, count=count, diversify_by_city=True)

    market_results: list[MarketResult] = []
    total_qualifying = 0
    total_sourced = 0
    for city, sector in markets:
        r = process_market(db, city, sector, req.country, limit, min_score)
        total_qualifying += len(r["qualifying_leads"])
        total_sourced += r["total_sourced"]
        market_results.append(MarketResult(
            city=r["city"], industry=r["industry"],
            total_sourced=r["total_sourced"],
            qualifying=len(r["qualifying_leads"]),
            leads=r["qualifying_leads"],
        ))

    return SweepResult(
        markets_worked=len(market_results),
        total_sourced=total_sourced,
        total_qualifying=total_qualifying,
        markets=market_results,
    )


@app.get("/markets/stats", dependencies=[HermesAuth])
def markets_stats(db: Session = Depends(get_db)):
    """Yield table across the whole market universe + the recommended next market.
    Hermes uses this to pick markets intelligently."""
    return get_coverage_stats(db)
