"""
Vision judgment — the one paid step.

Captures a screenshot (Playwright) and makes a SINGLE structured LLM call that
returns everything at once:
  - visual datedness score (0-100)
  - the specific visible problems an owner would recognize
  - a tailored one-line outreach pitch

This call only runs on candidates that survive the cheap deterministic pre-filter,
keeping vision spend proportional to qualified leads.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Optional

from app.config import settings

log = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]")
_SCREENSHOT_DIR = "/tmp/lyvica_screenshots"

_VISION_PROMPT = """You are evaluating a local business website screenshot to judge whether the business is a good prospect for a website redesign service.

Here is what automated checks already found about this site:
{evidence}

Look at the screenshot and respond with ONLY a JSON object:
{{
  "datedness": <integer 0-100, where 0=modern/current design, 100=extremely outdated>,
  "visible_problems": [<up to 3 short strings: problems a non-technical owner would immediately recognize when shown, e.g. "tiny text that's hard to read", "looks like it's from the early 2010s", "cluttered, hard to find contact info">],
  "pitch": "<one friendly, specific, non-insulting sentence Manuel could use to open a conversation — reference the single most compelling visible issue, do not exaggerate or promise results>"
}}

Judge datedness on: layout, typography, color, imagery style, spacing, and overall modernity. Be honest — a clean modern site should score low even if simple."""


def _slug(url: str) -> str:
    s = url.replace("https://", "").replace("http://", "").rstrip("/")
    return _SLUG_RE.sub("_", s)[:80]


def capture_screenshot(url: str) -> tuple[Optional[str], str]:
    """
    Capture a screenshot with Playwright. Returns (path, rendered_html).
    rendered_html is the post-JS DOM — used to detect JS-rendered builders
    (Wix/Squarespace) that the raw HTTP fetch misses. Empty string on failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright not installed — screenshot skipped")
        return None, ""

    try:
        os.makedirs(_SCREENSHOT_DIR, exist_ok=True)
    except OSError as exc:
        log.warning("cannot create screenshot dir: %s", exc)
        return None, ""

    path = os.path.join(_SCREENSHOT_DIR, f"{_slug(url)}_{int(time.time())}.png")
    rendered_html = ""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="LyvicaBot/1.0 (+https://lyvica.com/bot)",
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
            except Exception:
                page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            page.screenshot(path=path, full_page=False)
            try:
                rendered_html = page.content() or ""
            except Exception:
                rendered_html = ""
            browser.close()
        return path, rendered_html
    except Exception as exc:
        log.warning("screenshot failed for %s: %s", url, exc)
        return None, rendered_html


def _evidence_summary(evidence: dict) -> str:
    """Compact human-readable evidence string for the vision prompt."""
    parts = []
    psi = evidence.get("pagespeed_mobile")
    if psi is not None:
        parts.append(f"- Mobile PageSpeed score: {psi}/100" + (" (very slow)" if psi < 50 else ""))
    if evidence.get("has_viewport") is False:
        parts.append("- No mobile viewport tag (likely not responsive)")
    if not evidence.get("https"):
        parts.append("- No HTTPS (browsers show 'Not Secure')")
    yr = evidence.get("footer_copyright_year")
    if yr:
        parts.append(f"- Footer copyright year: {yr}")
    cms = evidence.get("cms")
    if cms:
        ver = evidence.get("cms_version")
        parts.append(f"- CMS: {cms}{(' ' + ver) if ver else ''}")
    last = evidence.get("last_significant_change")
    if last:
        parts.append(f"- Last significant change (Wayback): {last[:10]}")
    return "\n".join(parts) if parts else "- No notable automated findings"


def judge_visual(screenshot_path: str, evidence: dict) -> dict:
    """
    Single vision call → {datedness, visible_problems, pitch, error}.
    """
    out = {"datedness": None, "visible_problems": [], "pitch": None, "error": None}

    if not settings.GATEWAY_API_KEY:
        out["error"] = "GATEWAY_API_KEY not set"
        return out
    try:
        from openai import OpenAI
    except ImportError:
        out["error"] = "openai SDK not installed"
        return out

    try:
        b64 = base64.standard_b64encode(open(screenshot_path, "rb").read()).decode()
    except OSError as exc:
        out["error"] = f"cannot read screenshot: {exc}"
        return out

    client = OpenAI(api_key=settings.GATEWAY_API_KEY, base_url=settings.GATEWAY_BASE_URL)
    prompt = _VISION_PROMPT.format(evidence=_evidence_summary(evidence))

    try:
        resp = client.chat.completions.create(
            model=settings.VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=400,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as exc:
        out["error"] = f"vision call failed: {exc}"
        log.warning("vision call failed: %s", exc)
        return out

    # Strip markdown fences, parse JSON
    txt = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    txt = re.sub(r"\s*```$", "", txt, flags=re.MULTILINE)
    try:
        parsed = json.loads(txt)
        if parsed.get("datedness") is not None:
            out["datedness"] = int(parsed["datedness"])
        out["visible_problems"] = parsed.get("visible_problems", []) or []
        out["pitch"] = parsed.get("pitch")
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        out["error"] = f"could not parse vision JSON: {exc}. Raw: {raw[:200]}"
        log.warning("vision parse error: %s", exc)

    return out


def run_vision(website_url: str, evidence: dict) -> dict:
    """
    Screenshot + judge. Returns {datedness, visible_problems, pitch, error,
    rendered_html}. rendered_html lets the caller re-check for JS-rendered
    DIY builders the static fetch missed.
    """
    path, rendered_html = capture_screenshot(website_url)
    if not path:
        return {"datedness": None, "visible_problems": [], "pitch": None,
                "error": "screenshot unavailable", "rendered_html": rendered_html}
    result = judge_visual(path, evidence)
    result["rendered_html"] = rendered_html
    return result
