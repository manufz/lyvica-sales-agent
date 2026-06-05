from __future__ import annotations

import logging
import time
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.displayName,places.formattedAddress,places.websiteUri,"
    "places.id,nextPageToken"
)
_MAX_PAGES = 3  # Google Places caps text search at ~60 results (3 × 20)


def _domain_of(url: str) -> str:
    p = urlparse(url if url.startswith(("http://", "https://")) else f"https://{url}")
    return (p.netloc or p.path).removeprefix("www.").lower()


def source_leads(
    city: str,
    industry: str,
    country: Optional[str] = None,
    limit: int = 10,
    exclude_domains: Optional[set[str]] = None,
) -> dict:
    """
    Find local businesses via Google Places Text Search, paginating through all
    available pages and skipping businesses already known (exclude_domains) so
    each run surfaces FRESH leads and coverage advances over time.

    Returns:
        {
          "leads": [ {company_name, website_url, city, country, industry, address}, ... ],
          "exhausted": bool,   # True when Places had no more pages to give
          "pages": int,        # pages fetched
          "seen_total": int,   # businesses Places returned (incl. skipped)
        }
    """
    exclude_domains = {d.lower() for d in (exclude_domains or set())}

    if not settings.GOOGLE_PLACES_API_KEY:
        log.warning("GOOGLE_PLACES_API_KEY not set — skipping sourcing")
        return {"leads": [], "exhausted": True, "pages": 0, "seen_total": 0}

    location = f"{city}, {country}" if country else city
    query = f"{industry} in {location}"
    headers = {
        "X-Goog-Api-Key": settings.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": _FIELD_MASK,
    }

    results: list[dict] = []
    seen_domains: set[str] = set()
    seen_total = 0
    page_token: Optional[str] = None
    pages = 0
    exhausted = False

    with httpx.Client(timeout=20) as client:
        while len(results) < limit and pages < _MAX_PAGES:
            payload: dict = {"textQuery": query, "pageSize": 20, "languageCode": "en"}
            if page_token:
                payload["pageToken"] = page_token
            try:
                r = client.post(_PLACES_URL, json=payload, headers=headers)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                log.error("Google Places API error (page %d): %s", pages + 1, exc)
                break

            places = data.get("places", []) or []
            for place in places:
                seen_total += 1
                website = (place.get("websiteUri") or "").strip()
                name = (place.get("displayName", {}) or {}).get("text", "").strip()
                if not website or not name:
                    continue
                domain = _domain_of(website)
                if not domain or domain in exclude_domains or domain in seen_domains:
                    continue
                seen_domains.add(domain)
                results.append({
                    "company_name": name,
                    "website_url": website,
                    "city": city,
                    "country": country,
                    "industry": industry,
                    "address": (place.get("formattedAddress") or "").strip(),
                })
                if len(results) >= limit:
                    break

            pages += 1
            page_token = data.get("nextPageToken")
            if not page_token:
                exhausted = True
                break
            # New Places page tokens need a brief moment to become valid.
            time.sleep(2)

    log.info("sourced %d fresh leads for '%s' in '%s' (%d pages, %d seen, exhausted=%s)",
             len(results), industry, city, pages, seen_total, exhausted)
    return {"leads": results, "exhausted": exhausted, "pages": pages, "seen_total": seen_total}
