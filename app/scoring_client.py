from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_FALLBACK = {
    "score": None,
    "tier": "unknown",
    "confidence": None,
    "subscores": {},
    "pitch_angles": [],
    "scoring_payload": {},
}


def score_domain(
    domain: str,
    company_name: Optional[str] = None,
    city: Optional[str] = None,
    industry: Optional[str] = None,
) -> dict:
    """
    Calls lyvica-scoring POST /api/score with form data.
    The endpoint streams SSE; we collect the first 'result' event for this domain.

    If the endpoint path or request format changes, update here only.
    """
    url = f"{settings.LYVICA_SCORING_URL}/api/score"
    try:
        with httpx.Client(timeout=60) as client:
            with client.stream(
                "POST",
                url,
                data={"domains_text": domain, "min_score": 0, "concurrency": 1},
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = json.loads(line[len("data:"):].strip())
                    if payload.get("type") == "result":
                        lead = payload["lead"]
                        return {
                            # lyvica-scoring uses rebuild_opportunity_score
                            "score": lead.get("rebuild_opportunity_score"),
                            "tier": lead.get("tier", "unknown"),
                            "confidence": lead.get("confidence"),
                            "subscores": lead.get("subscores", {}),
                            "pitch_angles": lead.get("pitch_angles", []),
                            "scoring_payload": lead,
                        }
        # No result event received
        return {**_FALLBACK, "error": "no result from scoring stream"}
    except httpx.HTTPStatusError as exc:
        log.warning("scoring HTTP error %s: %s", exc.response.status_code, exc)
        return {**_FALLBACK, "error": f"HTTP {exc.response.status_code}"}
    except Exception as exc:
        log.warning("scoring unavailable: %s", exc)
        return {**_FALLBACK, "error": str(exc)}
