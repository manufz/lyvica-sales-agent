"""
Deterministic, synchronous signal collection for website scoring.

Everything here is free or near-free (HTTP calls + CPU). No LLM.
These run on every candidate as a cheap pre-filter before the paid vision call.
"""
from __future__ import annotations

import logging
import re
import socket
import ssl
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings

log = logging.getLogger(__name__)

_UA = "LyvicaBot/1.0 (+https://lyvica.com/bot)"
_PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_CDX_URL = "http://web.archive.org/cdx/search/cdx"

_COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)[^\d]{0,30}(\d{4})", re.IGNORECASE)
_GENERATOR_RE = re.compile(
    r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE
)

# Free tech fingerprints (subset — enough to flag modern vs ancient)
_CMS_KEYWORDS = {"wordpress", "drupal", "joomla", "shopify", "squarespace",
                 "wix", "webflow", "ghost", "magento", "typo3", "prestashop"}
_HTML_TECH_PATTERNS: list[tuple[str, str]] = [
    ("WordPress", r"wp-(?:content|includes|json)[/\"']"),
    ("Drupal", r"(?:Drupal\.settings|/sites/(?:all|default)/)"),
    ("Joomla", r"/components/com_[a-z]"),
    ("Squarespace", r"static\d*\.squarespace\.com"),
    ("Shopify", r"cdn\.shopify\.com"),
    ("Webflow", r"webflow\.com"),
    ("Wix", r"static\.wixstatic\.com"),
    ("jQuery/1", r"jquery[.-]1\.\d+"),
    ("jQuery/2", r"jquery[.-]2\.\d+"),
    ("Flash", r'\.swf["\' ]|<embed[^>]+\.swf'),
    ("React", r'(?:react\.production\.min\.js|"__NEXT_DATA__")'),
    ("Vue.js", r'(?:vue\.min\.js|"__vue_app__")'),
]


def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def fetch_page(url: str, timeout: float = 15.0) -> dict:
    """Fetch homepage HTML + headers."""
    url = _normalize_url(url)
    out = {"html": "", "headers": {}, "final_url": url, "status_code": None, "error": None}
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": _UA}) as c:
            r = c.get(url)
            out["status_code"] = r.status_code
            out["headers"] = dict(r.headers)
            out["html"] = r.text
            out["final_url"] = str(r.url)
    except Exception as exc:
        out["error"] = str(exc)
        log.debug("fetch failed %s: %s", url, exc)
    return out


def parse_html_signals(html: str) -> dict:
    """Extract viewport, OG, schema, meta description, copyright year."""
    out = {
        "viewport_meta": False, "open_graph": False, "schema_org": False,
        "meta_description": False, "footer_copyright_year": None,
    }
    if not html:
        return out
    try:
        soup = BeautifulSoup(html, "html.parser")
        out["viewport_meta"] = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}) is not None
        out["open_graph"] = soup.find("meta", attrs={"property": re.compile(r"^og:", re.I)}) is not None
        json_ld = soup.find("script", attrs={"type": re.compile(r"application/ld\+json", re.I)})
        microdata = soup.find(attrs={"itemscope": True})
        out["schema_org"] = json_ld is not None or microdata is not None
        out["meta_description"] = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)}) is not None

        # copyright year — footer-ish elements first
        candidates: list[str] = []
        for tag in soup.find_all(["footer", "div", "p", "span", "small"]):
            matches = _COPYRIGHT_RE.findall(tag.get_text(separator=" "))
            if matches:
                candidates.extend(matches)
                break
        if not candidates:
            candidates = _COPYRIGHT_RE.findall(soup.get_text(separator=" "))
        if candidates:
            try:
                out["footer_copyright_year"] = max(int(y) for y in candidates)
            except ValueError:
                pass
    except Exception as exc:
        log.debug("html parse error: %s", exc)
    return out


# DIY website builders — owner-built, low attachment, high-propensity "easy sell".
# (label, [html/header substrings to match, lowercased])
_DIY_BUILDERS: list[tuple[str, list[str]]] = [
    ("Wix",         ["wixstatic.com", "wix.com", "_wixcss", "x-wix-"]),
    ("Squarespace", ["squarespace.com", "squarespace-cdn", "static1.squarespace"]),
    ("GoDaddy",     ["godaddy", "secureserver.net", "websitebuilder", "mysite-cdn", "img1.wsimg.com"]),
    ("Weebly",      ["weebly.com", "editmysite.com", "weeblycloud"]),
    ("Jimdo",       ["jimdo.com", "jimdofree", "jimstatic.com"]),
    ("Strikingly",  ["strikingly.com", "strikinglycdn"]),
    ("Site123",     ["site123", "isu.pub"]),
    ("Google Sites",["sites.google.com", "gstatic.com/sites"]),
    ("Webnode",     ["webnode.com", "wnode"]),
]


def detect_diy_builder(html: str, headers: dict, cms: Optional[str]) -> Optional[str]:
    """
    Return the DIY builder name if the site is built on a consumer website
    builder, else None. These are strong 'easy sell' buying signals: the owner
    DIY'd the site (low attachment) but already values having a web presence.
    """
    corpus = (html or "").lower()
    header_blob = " ".join(f"{k}:{v}" for k, v in (headers or {}).items()).lower()
    cms_l = (cms or "").lower()
    for label, needles in _DIY_BUILDERS:
        if label.lower() in cms_l:
            return label
        for n in needles:
            if n in corpus or n in header_blob:
                return label
    return None


def detect_tech(html: str, headers: dict) -> dict:
    """Free HTML/header tech detection. Returns {technologies, cms, cms_version}."""
    techs: list[str] = []
    cms_name: Optional[str] = None
    cms_ver: Optional[str] = None

    if html:
        gen = _GENERATOR_RE.search(html)
        if gen:
            parts = gen.group(1).strip().split(" ", 1)
            name = parts[0]
            ver = parts[1] if len(parts) > 1 else None
            techs.append(f"{name}/{ver}" if ver else name)
            if any(kw in name.lower() for kw in _CMS_KEYWORDS):
                cms_name, cms_ver = name, ver
        for label, pat in _HTML_TECH_PATTERNS:
            if re.search(pat, html, re.IGNORECASE) and label not in techs:
                techs.append(label)
                if cms_name is None and any(kw in label.lower() for kw in _CMS_KEYWORDS):
                    cms_name = label

    server = headers.get("server") or headers.get("Server")
    if server:
        techs.append(f"Server/{server}")

    return {"technologies": list(dict.fromkeys(techs)), "cms": cms_name, "cms_version": cms_ver}


def fetch_pagespeed(url: str) -> dict:
    """Google PageSpeed Insights — MOBILE strategy. Returns performance score + viewport audit."""
    out = {"mobile_score": None, "has_viewport": None, "error": None}
    if not settings.PAGESPEED_API_KEY:
        out["error"] = "no PAGESPEED_API_KEY"
        return out
    params = {"url": _normalize_url(url), "strategy": "mobile", "key": settings.PAGESPEED_API_KEY}
    try:
        with httpx.Client(timeout=60.0) as c:
            r = c.get(_PSI_URL, params=params)
            r.raise_for_status()
            data = r.json()
        lh = data.get("lighthouseResult", {})
        perf = lh.get("categories", {}).get("performance", {}).get("score")
        if perf is not None:
            out["mobile_score"] = round(perf * 100)
        vp = lh.get("audits", {}).get("viewport", {}).get("score")
        if vp is not None:
            out["has_viewport"] = vp == 1
    except Exception as exc:
        out["error"] = str(exc)
        log.debug("PSI failed %s: %s", url, exc)
    return out


def check_ssl(domain: str) -> dict:
    """TLS/HTTPS check via socket."""
    out = {"https": False, "cert_valid": False, "error": None}
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain):
                out["https"] = True
                out["cert_valid"] = True
    except ssl.SSLCertVerificationError as exc:
        out["https"] = True
        out["cert_valid"] = False
        out["error"] = f"cert invalid: {exc}"
    except Exception as exc:
        out["error"] = str(exc)
    return out


def fetch_wayback(domain: str) -> dict:
    """Wayback CDX — most recent snapshot timestamp."""
    out = {"last_significant_change": None, "error": None}
    today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    params = {
        "url": domain, "output": "json", "limit": "1", "fl": "timestamp,statuscode",
        "filter": "statuscode:200", "from": "20150101", "to": today,
        "collapse": "digest", "fastLatest": "true",
    }
    try:
        with httpx.Client(timeout=30.0) as c:
            r = c.get(_CDX_URL, params=params)
            r.raise_for_status()
            data = r.json()
        rows = [x for x in (data if isinstance(data, list) else []) if x and x[0] != "timestamp"]
        if rows:
            dt = datetime.strptime(rows[-1][0], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            out["last_significant_change"] = dt.isoformat()
    except Exception as exc:
        out["error"] = str(exc)
        log.debug("wayback failed %s: %s", domain, exc)
    return out


def collect_signals(domain: str, website_url: str) -> dict:
    """
    Run all deterministic signals. Returns a flat evidence dict.
    Each signal fails independently — partial data never crashes the whole.
    """
    page = fetch_page(website_url)
    html = page.get("html", "") or ""
    headers = page.get("headers", {}) or {}

    html_signals = parse_html_signals(html)
    tech = detect_tech(html, headers)
    diy_builder = detect_diy_builder(html, headers, tech["cms"])
    psi = fetch_pagespeed(website_url)
    ssl_info = check_ssl(domain)
    wayback = fetch_wayback(domain)

    return {
        "viewport_meta": html_signals["viewport_meta"],
        "open_graph": html_signals["open_graph"],
        "schema_org": html_signals["schema_org"],
        "meta_description": html_signals["meta_description"],
        "footer_copyright_year": html_signals["footer_copyright_year"],
        "technologies": tech["technologies"],
        "cms": tech["cms"],
        "cms_version": tech["cms_version"],
        "diy_builder": diy_builder,
        "pagespeed_mobile": psi["mobile_score"],
        "has_viewport": psi["has_viewport"],
        "https": ssl_info["https"],
        "cert_valid": ssl_info["cert_valid"],
        "last_significant_change": wayback["last_significant_change"],
        "final_url": page.get("final_url", website_url),
        "fetch_error": page.get("error"),
    }
