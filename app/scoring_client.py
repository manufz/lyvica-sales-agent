"""
Scoring client — now a thin wrapper around the in-process scoring module.

Previously this made an HTTP call to a separate lyvica-scoring service.
Scoring is now merged in (app.scoring) — direct function call, no network hop,
no SSE parsing, no second service to keep alive.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.scoring import score_domain as _score_domain

log = logging.getLogger(__name__)

_FALLBACK = {
    "score": None,
    "tier": "unknown",
    "confidence": None,
    "subscores": {},
    "pitch_angles": [],
    "visible_problems": [],
    "scoring_payload": {},
}


def score_domain(
    domain: str,
    company_name: Optional[str] = None,
    city: Optional[str] = None,
    industry: Optional[str] = None,
    website_url: Optional[str] = None,
) -> dict:
    """Score a domain via the in-process scoring module. Never raises."""
    try:
        return _score_domain(
            domain=domain,
            website_url=website_url,
            company_name=company_name,
            city=city,
            industry=industry,
        )
    except Exception as exc:
        log.error("scoring failed for %s: %s", domain, exc)
        return {**_FALLBACK, "error": str(exc)}
