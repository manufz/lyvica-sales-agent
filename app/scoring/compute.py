"""
Scoring computation — turns raw signals into a rebuild-opportunity score.

Key fixes vs the original lyvica-scoring:
  1. MOBILE uses the real PSI mobile score, not just the viewport-tag boolean.
  2. Reweighted toward OWNER-VISIBLE problems (mobile, visual, security, freshness)
     and away from owner-invisible plumbing (tech obsolescence, SEO tags).
  3. Minimum-confidence gate: refuses to return a usable score when the two core
     signals (mobile + visual) are both missing or too little was measured.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# Weights sum to 1.0. Tilted toward what a business owner can SEE and would pay to fix.
_WEIGHTS = {
    "mobile":            0.30,   # "doesn't work on my phone"  — owner-visible, core
    "visual_datedness":  0.30,   # "looks outdated"            — owner-visible, core
    "security":          0.15,   # "Not Secure warning"        — owner-visible
    "content_freshness": 0.15,   # "looks abandoned"           — owner-relatable
    "tech_obsolescence": 0.05,   # owner-invisible plumbing    — demoted
    "seo_hygiene":       0.05,   # owner-invisible plumbing    — minimal
}

# A score is only trustworthy if enough was measured AND at least one core
# (owner-visible) signal is present.
_MIN_MEASURED_WEIGHT = 0.50
_CORE_SIGNALS = ("mobile", "visual_datedness")

_FRESHNESS_BREAKPOINTS = [(0.0, 0.0), (1.0, 0.0), (2.0, 40.0), (3.0, 70.0), (4.0, 100.0)]


def _interpolate(x: float, bp: list[tuple[float, float]]) -> float:
    if x <= bp[0][0]:
        return bp[0][1]
    if x >= bp[-1][0]:
        return bp[-1][1]
    for i in range(len(bp) - 1):
        x0, y0 = bp[i]
        x1, y1 = bp[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return bp[-1][1]


def _mobile_subscore(pagespeed_mobile: Optional[int], has_viewport: Optional[bool],
                     viewport_meta: bool) -> Optional[float]:
    """
    FIXED mobile signal.
    - No viewport tag at all  → 100 (definitely not mobile-ready)
    - Otherwise use the real PSI mobile score: problem = 100 - score
      (PSI 11 → problem 89; PSI 90 → problem 10). This is the actual mobile
      experience, which the old viewport-only check completely ignored.
    - If PSI unavailable, fall back to viewport boolean only.
    """
    no_viewport = (has_viewport is False) or (viewport_meta is False and has_viewport is None)
    if no_viewport:
        return 100.0
    if pagespeed_mobile is not None:
        return round(max(0.0, 100.0 - float(pagespeed_mobile)), 2)
    return None  # has viewport but no PSI — can't quantify, skip


def _security_subscore(https: bool, cert_valid: bool) -> float:
    if not https:
        return 100.0
    if not cert_valid:
        return 80.0
    return 0.0


def _content_freshness_subscore(last_change_iso: Optional[str],
                                footer_year: Optional[int]) -> Optional[float]:
    now = datetime.now(tz=timezone.utc)
    years_old: Optional[float] = None
    if last_change_iso:
        try:
            dt = datetime.fromisoformat(last_change_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            years_old = (now - dt).days / 365.25
        except ValueError:
            pass
    if years_old is None and footer_year is not None:
        years_old = max(0.0, now.year - footer_year)
    if years_old is None:
        return None
    val = round(_interpolate(years_old, _FRESHNESS_BREAKPOINTS), 2)
    return val if val > 0 else None


def _tech_obsolescence_subscore(technologies: list[str], cms: Optional[str],
                                cms_version: Optional[str]) -> Optional[float]:
    corpus = " ".join(technologies).lower() + " " + (cms or "").lower() + " " + (cms_version or "").lower()
    modern = ["react", "next", "vue", "svelte", "astro", "tailwind", "wordpress/6",
              "wordpress/5", "php/8", "shopify", "webflow", "framer", "bootstrap/5"]
    if any(m in corpus for m in modern):
        return None  # modern stack → no penalty
    ancient = {"flash": 100.0, "silverlight": 80.0, "jquery/1": 80.0, "jquery/2": 60.0,
               "php/5": 80.0, "php/7": 50.0, "bootstrap/3": 50.0, "mootools": 60.0}
    score = max((v for k, v in ancient.items() if k in corpus), default=0.0)
    return score if score > 0 else None


def _seo_subscore(open_graph: bool, meta_description: bool, schema_org: bool) -> Optional[float]:
    score = sum(34.0 for s in (open_graph, meta_description, schema_org) if not s)
    return min(100.0, score) if score > 0 else None


def compute_score(evidence: dict, visual_datedness: Optional[float]) -> dict:
    """
    Combine all signals into {score, tier, confidence, subscores, scoreable}.
    """
    subscores = {
        "mobile": _mobile_subscore(
            evidence.get("pagespeed_mobile"),
            evidence.get("has_viewport"),
            evidence.get("viewport_meta", False),
        ),
        "visual_datedness": float(visual_datedness) if visual_datedness is not None else None,
        "security": _security_subscore(
            evidence.get("https", False), evidence.get("cert_valid", False)
        ),
        "content_freshness": _content_freshness_subscore(
            evidence.get("last_significant_change"), evidence.get("footer_copyright_year")
        ),
        "tech_obsolescence": _tech_obsolescence_subscore(
            evidence.get("technologies", []), evidence.get("cms"), evidence.get("cms_version")
        ),
        "seo_hygiene": _seo_subscore(
            evidence.get("open_graph", False),
            evidence.get("meta_description", False),
            evidence.get("schema_org", False),
        ),
    }

    measured_weight = sum(_WEIGHTS[k] for k, v in subscores.items() if v is not None)
    if measured_weight == 0:
        return {"score": None, "tier": "unknown", "confidence": 0.0,
                "subscores": subscores, "scoreable": False}

    weighted = sum(_WEIGHTS[k] * v for k, v in subscores.items() if v is not None)
    score = round(weighted / measured_weight)
    confidence = round(measured_weight, 3)

    # Confidence gate: need enough measured AND at least one core signal present
    has_core = any(subscores[k] is not None for k in _CORE_SIGNALS)
    scoreable = measured_weight >= _MIN_MEASURED_WEIGHT and has_core

    if not scoreable:
        tier = "unknown"
    elif score >= 70:
        tier = "hot"
    elif score >= 50:
        tier = "warm"
    else:
        tier = "cold"

    return {
        "score": float(score),
        "tier": tier,
        "confidence": confidence,
        "subscores": subscores,
        "scoreable": scoreable,
    }
