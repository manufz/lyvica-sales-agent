"""
LLM-written, per-lead outreach — replaces the static template with a real email
the agent model writes from each lead's specifics. Falls back to the template if
the model call fails, so sending never breaks.

All emails get the compliance footer (identity + opt-out + address-when-set).
"""
from __future__ import annotations

import logging
from typing import Optional

from app.config import settings
from app.outreach_templates import (
    derive_desired_action,
    derive_primary_issue,
    render_followup,
    render_initial,
)

log = logging.getLogger(__name__)


# ── Compliance footer (CAN-SPAM: identity + opt-out + physical address) ────────

def build_footer(industry: Optional[str], city: Optional[str]) -> str:
    ident = settings.COMPLIANCE_NAME
    bits = [settings.COMPLIANCE_WEBSITE, settings.COMPLIANCE_X]
    links = " · ".join([b for b in bits if b])
    loc = settings.COMPLIANCE_ADDRESS or settings.COMPLIANCE_CITY
    reason = (
        f'You received this because we research local '
        f'{industry or "business"} websites in {city or "your area"}.'
    )
    lines = [
        "—",
        f"{ident}" + (f" · {links}" if links else ""),
        loc,
        reason,
        'Reply "no" and we will never email you again.',
    ]
    return "\n".join(b for b in lines if b)


def _with_footer(body: str, lead) -> str:
    return body.rstrip() + "\n\n" + build_footer(
        getattr(lead, "industry", None), getattr(lead, "city", None)
    )


def _lead_facts(lead) -> str:
    issue = lead.primary_issue or derive_primary_issue(lead.pitch_angles or [])
    signals = ", ".join(lead.buying_signals or []) or "none"
    return (
        f"Company: {lead.company_name}\n"
        f"Website: {lead.website_url}\n"
        f"Industry: {lead.industry or 'local business'}\n"
        f"City: {lead.city or 'unknown'}\n"
        f"Score/tier: {lead.score}/{lead.tier}\n"
        f"Main visible issue: {issue}\n"
        f"Buying signals: {signals}\n"
    )


_SYSTEM = (
    "You are Manuel from Lyvica, a small studio that modernizes outdated local "
    "business websites. You write short, warm, specific cold outreach emails. "
    "Rules: under 110 words; reference the ONE concrete visible issue naturally; "
    "ask permission to send a free 3-point improvement snapshot; no fake "
    "compliments; no guarantees or revenue claims; no price; no links in the body; "
    "plain text. Sign as 'Manuel'. Output strictly as JSON: "
    '{"subject": "...", "body": "..."} and nothing else.'
)


def _chat_json(messages: list[dict]) -> Optional[dict]:
    if not settings.GATEWAY_API_KEY:
        return None
    try:
        from openai import OpenAI
        import json, re
        client = OpenAI(api_key=settings.GATEWAY_API_KEY, base_url=settings.GATEWAY_BASE_URL)
        r = client.chat.completions.create(
            model=settings.OUTREACH_MODEL, messages=messages, max_tokens=500,
        )
        raw = r.choices[0].message.content or ""
        txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
        return json.loads(txt)
    except Exception as exc:
        log.warning("outreach LLM failed (%s) — falling back to template", exc)
        return None


def write_initial(lead) -> tuple[str, str]:
    """LLM-write the first outreach email. Footer appended. Template fallback."""
    parsed = _chat_json([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "Write the first outreach email.\n\n" + _lead_facts(lead)},
    ])
    if parsed and parsed.get("subject") and parsed.get("body"):
        return parsed["subject"].strip(), _with_footer(parsed["body"].strip(), lead)

    # Fallback: deterministic template
    subject, body = render_initial(
        company_name=lead.company_name,
        industry=lead.industry or "local",
        city=lead.city or "your area",
        primary_issue=lead.primary_issue or derive_primary_issue(lead.pitch_angles or []),
        desired_action=lead.desired_action or derive_desired_action(lead.industry),
    )
    return subject, _with_footer(body, lead)


def write_followup(lead) -> tuple[str, str]:
    """LLM-write a short follow-up. Footer appended. Template fallback."""
    parsed = _chat_json([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            "Write a SHORT follow-up to a first email that got no reply. "
            "Reference the same issue, stay friendly, one ask. "
            f"Keep the subject as 'Re: {lead.first_subject or 'your website'}'.\n\n"
            + _lead_facts(lead)
        )},
    ])
    if parsed and parsed.get("body"):
        subject = parsed.get("subject") or f"Re: {lead.first_subject or 'your website'}"
        return subject.strip(), _with_footer(parsed["body"].strip(), lead)

    subject, body = render_followup(
        company_name=lead.company_name,
        first_subject=lead.first_subject or "your website",
        primary_issue=lead.primary_issue or derive_primary_issue(lead.pitch_angles or []),
        desired_action=lead.desired_action or derive_desired_action(lead.industry),
    )
    return subject, _with_footer(body, lead)


def rewrite(lead, instruction: str) -> tuple[str, str]:
    """Revise the current draft per an operator instruction (the `edit` command)."""
    current = f"Current subject: {lead.first_subject}\nCurrent body:\n{lead.first_body}"
    parsed = _chat_json([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            f"Revise this outreach email per the instruction: \"{instruction}\".\n\n"
            f"{current}\n\nLead facts:\n{_lead_facts(lead)}"
        )},
    ])
    if parsed and parsed.get("body"):
        subject = parsed.get("subject") or lead.first_subject
        return subject.strip(), _with_footer(parsed["body"].strip(), lead)
    # If LLM fails, return current unchanged (caller keeps existing draft)
    return lead.first_subject, lead.first_body
