"""
Lyvica scoring module — merged into lyvica-sales-agent (no separate HTTP service).

Public API:
    score_domain(domain, website_url, company_name=None, city=None, industry=None)
        → dict with score, tier, confidence, subscores, pitch_angles,
          visible_problems, scoring_payload

Architecture (cost-optimized):
    1. Deterministic signals (free)          → app.scoring.signals
    2. Cheap pre-filter decides if vision is worth it
    3. Vision judgment (one paid LLM call)   → app.scoring.vision
    4. Weighted compute + confidence gate    → app.scoring.compute
"""
from __future__ import annotations

import logging
from typing import Optional

from app.scoring.compute import compute_score
from app.scoring.signals import collect_signals
from app.scoring.vision import run_vision

log = logging.getLogger(__name__)


def _vision_worth_running(evidence: dict) -> bool:
    """
    Cheap pre-filter: only spend a vision call when the deterministic signals
    suggest the site might be a candidate. Skip clearly-modern sites.

    Skip vision if ALL of: HTTPS valid + good mobile PSI (>=80) + recent copyright.
    Otherwise run it (the visual look is the deciding factor).
    """
    https_ok = evidence.get("https") and evidence.get("cert_valid")
    psi = evidence.get("pagespeed_mobile")
    psi_ok = psi is not None and psi >= 80
    yr = evidence.get("footer_copyright_year")
    from datetime import datetime, timezone
    current_year = datetime.now(tz=timezone.utc).year
    fresh = yr is not None and yr >= current_year - 1

    # Clearly modern on every cheap axis → don't spend vision
    if https_ok and psi_ok and fresh:
        return False
    return True


def _fallback_pitch_angles(subscores: dict) -> list[str]:
    """Deterministic pitch angles used only when vision is unavailable."""
    angles = []
    if (subscores.get("mobile") or 0) >= 60:
        angles.append("Site struggles on mobile — most local searches happen on phones")
    if (subscores.get("security") or 0) >= 100:
        angles.append("No HTTPS — visitors see a 'Not Secure' warning")
    if (subscores.get("content_freshness") or 0) >= 70:
        angles.append("Content looks stale — no significant update in years")
    return angles


def score_domain(
    domain: str,
    website_url: Optional[str] = None,
    company_name: Optional[str] = None,
    city: Optional[str] = None,
    industry: Optional[str] = None,
) -> dict:
    """Full scoring pipeline for one domain. Never raises — returns safe fallback."""
    url = website_url or f"https://{domain}"

    try:
        evidence = collect_signals(domain, url)
    except Exception as exc:
        log.error("signal collection failed for %s: %s", domain, exc)
        return {
            "score": None, "tier": "unknown", "confidence": 0.0,
            "subscores": {}, "pitch_angles": [], "visible_problems": [],
            "scoring_payload": {}, "error": str(exc),
        }

    # Vision only on plausible candidates (cost control)
    vision = {"datedness": None, "visible_problems": [], "pitch": None, "error": "skipped"}
    if _vision_worth_running(evidence):
        try:
            vision = run_vision(url, evidence)
        except Exception as exc:
            log.warning("vision failed for %s: %s", domain, exc)
            vision = {"datedness": None, "visible_problems": [], "pitch": None, "error": str(exc)}

    result = compute_score(evidence, vision.get("datedness"))

    # Pitch angles: prefer the vision-generated tailored pitch; fall back to deterministic
    pitch_angles: list[str] = []
    if vision.get("pitch"):
        pitch_angles.append(vision["pitch"])
    pitch_angles += [p for p in (vision.get("visible_problems") or []) if p]
    if not pitch_angles:
        pitch_angles = _fallback_pitch_angles(result["subscores"])

    return {
        "score": result["score"],
        "tier": result["tier"],
        "confidence": result["confidence"],
        "scoreable": result["scoreable"],
        "subscores": result["subscores"],
        "pitch_angles": pitch_angles,
        "visible_problems": vision.get("visible_problems") or [],
        "scoring_payload": {
            "evidence": evidence,
            "vision": vision,
            "subscores": result["subscores"],
        },
    }
