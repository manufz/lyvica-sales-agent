from __future__ import annotations
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_INSTAGRAM_RE = re.compile(r"https?://(?:www\.)?(?:instagram\.com|instagr\.am)/[\w.]+/?")

_CONTACT_KEYWORDS = {
    "contact", "kontakt", "impressum", "about", "team",
    "legal", "privacy", "reservation", "booking", "appointment",
    "termin", "quote", "datenschutz", "about-us",
}

_IGNORED_EMAIL_PATTERNS = re.compile(
    r"@(?:sentry\.|example\.|wix\.|wordpress\.|schema\.|googletagmanager\.|googleapis\.)",
    re.IGNORECASE,
)

_MAX_CANDIDATE_PAGES = 6


def _is_business_email(email: str) -> bool:
    free_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "gmx.at", "gmx.de", "gmx.net"}
    domain = email.split("@")[-1].lower()
    return domain not in free_domains


def _extract_emails(text: str) -> list[str]:
    found = _EMAIL_RE.findall(text)
    return [
        e.lower() for e in found
        if not _IGNORED_EMAIL_PATTERNS.search(e)
    ]


def _extract_instagram(soup: BeautifulSoup, text: str) -> str | None:
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        if "instagram.com/" in href or "instagr.am/" in href:
            m = _INSTAGRAM_RE.search(href)
            if m:
                return m.group(0).rstrip("/")
    m = _INSTAGRAM_RE.search(text)
    return m.group(0).rstrip("/") if m else None


def _has_contact_form(soup: BeautifulSoup) -> bool:
    for form in soup.find_all("form"):
        inputs = form.find_all(["input", "textarea"])
        for inp in inputs:
            name = (inp.get("name") or "").lower()
            type_ = (inp.get("type") or "").lower()
            if type_ == "email" or "email" in name or inp.name == "textarea":
                return True
    return False


def _candidate_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        text = tag.get_text(strip=True).lower()
        # skip non-http, anchors, external social, obvious assets
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        if any(href.endswith(ext) for ext in (".jpg", ".png", ".pdf", ".svg", ".css", ".js")):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        base_parsed = urlparse(base_url)
        # same host only
        if parsed.netloc and parsed.netloc != base_parsed.netloc:
            continue
        path_lower = parsed.path.lower()
        if full in seen:
            continue
        if any(kw in path_lower or kw in text for kw in _CONTACT_KEYWORDS):
            seen.add(full)
            candidates.append(full)
    return candidates[:_MAX_CANDIDATE_PAGES]


def _fetch(client: httpx.Client, url: str) -> str | None:
    try:
        r = client.get(url, timeout=10, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        log.debug("fetch failed %s: %s", url, exc)
        return None


def discover_contacts(website_url: str) -> dict:
    emails: list[str] = []
    instagram_url: str | None = None
    contact_form_url: str | None = None
    checked_urls: list[str] = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; LyvicaBot/1.0; +https://lyvica.com)"
        )
    }

    with httpx.Client(headers=headers) as client:
        html = _fetch(client, website_url)
        if not html:
            return {
                "email_addresses": [],
                "email": None,
                "contact_form_url": None,
                "instagram_url": None,
                "checked_urls": [],
            }

        checked_urls.append(website_url)
        soup = BeautifulSoup(html, "lxml")

        emails.extend(_extract_emails(html))
        if not instagram_url:
            instagram_url = _extract_instagram(soup, html)
        if not contact_form_url and _has_contact_form(soup):
            contact_form_url = website_url

        candidates = _candidate_links(soup, website_url)

        for url in candidates:
            if url in checked_urls:
                continue
            page_html = _fetch(client, url)
            if not page_html:
                continue
            checked_urls.append(url)
            page_soup = BeautifulSoup(page_html, "lxml")

            emails.extend(_extract_emails(page_html))
            if not instagram_url:
                instagram_url = _extract_instagram(page_soup, page_html)
            if not contact_form_url and _has_contact_form(page_soup):
                contact_form_url = url

    # Deduplicate, normalize, prefer business emails
    seen: set[str] = set()
    deduped: list[str] = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            deduped.append(e)

    business = [e for e in deduped if _is_business_email(e)]
    primary = business[0] if business else (deduped[0] if deduped else None)

    return {
        "email_addresses": deduped,
        "email": primary,
        "contact_form_url": contact_form_url,
        "instagram_url": instagram_url,
        "checked_urls": checked_urls,
    }
