from __future__ import annotations
"""
Deterministic template-based outreach drafts.
Hermes will usually rewrite these — keep them as clean starting points.
Replace with LLM calls later by swapping the functions below.
"""

_INITIAL_SUBJECT = "Quick idea for {company_name}'s website"

_INITIAL_BODY = """\
Hi {company_name},

I found {company_name} while looking at {industry} businesses in {city}.

I noticed {primary_issue}. On mobile, that can make it harder for potential customers to {desired_action}.

I made a quick snapshot with 3 simple website improvements and a sample homepage direction.

Want me to send it over?

Best,
Manuel

If this is not relevant, reply "no" and I will not contact you again.\
"""

_FOLLOWUP_SUBJECT = "Re: {first_subject}"

_FOLLOWUP_BODY = """\
Hi {company_name},

quick follow-up — the main opportunity I saw was {primary_issue}.

A simple improvement would be {specific_fix}, so visitors can more easily {desired_action}.

Want me to send the short snapshot?

Best,
Manuel\
"""


def render_initial(
    company_name: str,
    industry: str,
    city: str,
    primary_issue: str,
    desired_action: str,
) -> tuple[str, str]:
    subject = _INITIAL_SUBJECT.format(company_name=company_name)
    body = _INITIAL_BODY.format(
        company_name=company_name,
        industry=industry or "local",
        city=city or "your area",
        primary_issue=primary_issue,
        desired_action=desired_action,
    )
    return subject, body


def render_followup(
    company_name: str,
    first_subject: str,
    primary_issue: str,
    desired_action: str,
    specific_fix: str = "a faster, mobile-friendly layout",
) -> tuple[str, str]:
    subject = _FOLLOWUP_SUBJECT.format(first_subject=first_subject)
    body = _FOLLOWUP_BODY.format(
        company_name=company_name,
        primary_issue=primary_issue,
        specific_fix=specific_fix,
        desired_action=desired_action,
    )
    return subject, body


def derive_primary_issue(pitch_angles: list) -> str:
    """Pick the top pitch angle as the primary issue copy."""
    if pitch_angles:
        first = pitch_angles[0]
        if isinstance(first, dict):
            return first.get("issue") or first.get("angle") or str(first)
        return str(first)
    return "the website could be improved for mobile visitors"


def derive_desired_action(industry: str | None) -> str:
    mapping = {
        "dentist": "book an appointment",
        "restaurant": "make a reservation",
        "hotel": "check availability",
        "lawyer": "request a consultation",
        "gym": "sign up for a trial",
        "salon": "book a session",
    }
    if industry:
        for key, action in mapping.items():
            if key in (industry or "").lower():
                return action
    return "get in touch"
