from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = "places.displayName,places.formattedAddress,places.websiteUri,places.id"


def source_leads(
    city: str,
    industry: str,
    country: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """
    Find local businesses via Google Places Text Search.
    Returns a list of dicts with company_name, website_url, city, industry.
    Only returns businesses that have a website URL.
    """
    if not settings.GOOGLE_PLACES_API_KEY:
        log.warning("GOOGLE_PLACES_API_KEY not set — skipping sourcing")
        return []

    location = f"{city}, {country}" if country else city
    query = f"{industry} in {location}"

    payload = {
        "textQuery": query,
        "maxResultCount": min(limit * 2, 20),  # fetch extra to account for missing websites
        "languageCode": "en",
    }

    try:
        with httpx.Client(timeout=15) as client:
            r = client.post(
                _PLACES_URL,
                json=payload,
                headers={
                    "X-Goog-Api-Key": settings.GOOGLE_PLACES_API_KEY,
                    "X-Goog-FieldMask": _FIELD_MASK,
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        log.error("Google Places API error: %s", exc)
        return []

    results = []
    for place in data.get("places", []):
        website = place.get("websiteUri", "").strip()
        if not website:
            continue  # skip places with no website — nothing to score

        name = place.get("displayName", {}).get("text", "").strip()
        address = place.get("formattedAddress", "").strip()
        if not name:
            continue

        results.append({
            "company_name": name,
            "website_url": website,
            "city": city,
            "country": country,
            "industry": industry,
            "address": address,
        })

        if len(results) >= limit:
            break

    log.info("sourced %d leads for '%s' in '%s'", len(results), industry, city)
    return results
