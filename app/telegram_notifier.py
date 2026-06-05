from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"


def _send(text: str, parse_mode: str = "HTML") -> bool:
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping notification")
        return False
    url = _TELEGRAM_URL.format(token=settings.TELEGRAM_BOT_TOKEN)
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json={
                "chat_id": settings.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            })
            r.raise_for_status()
            return True
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)
        return False


def notify_pipeline_results(
    city: str,
    industry: str,
    total_sourced: int,
    qualifying: list[dict],
) -> None:
    """Send a formatted lead summary to Telegram."""
    now = datetime.now(timezone.utc).strftime("%b %d %Y, %H:%M UTC")

    if not qualifying:
        _send(
            f"🔍 <b>Lyvica Pipeline — {industry.title()}s in {city}</b>\n"
            f"📅 {now}\n\n"
            f"Sourced {total_sourced} businesses — <b>no qualifying leads</b> found.\n"
            f"(Need email/form/Instagram + score ≥ threshold)"
        )
        return

    lines = [
        f"🎯 <b>Lyvica Pipeline — {industry.title()}s in {city}</b>",
        f"📅 {now}",
        f"",
        f"Found <b>{total_sourced}</b> businesses → <b>{len(qualifying)}</b> qualifying leads",
        f"",
    ]

    for i, lead in enumerate(qualifying, 1):
        score = lead.get("score")
        tier = (lead.get("tier") or "unknown").upper()
        score_str = f"{int(score)}" if score is not None else "?"

        channel_icons = {"email": "📧", "contact_form": "📝", "instagram": "📸", "none": "❓"}
        channel = lead.get("recommended_channel", "none")
        channel_icon = channel_icons.get(channel, "❓")

        contact = (
            lead.get("email")
            or lead.get("contact_form_url")
            or lead.get("instagram_url")
            or "—"
        )

        issue = lead.get("primary_issue") or "website could be improved"
        subject = lead.get("first_subject") or "—"
        body_preview = (lead.get("first_body") or "")[:200].replace("\n", " ")

        lines += [
            f"{'─' * 30}",
            f"<b>{i}. {lead['company_name']}</b>",
            f"🌐 {lead.get('website_url', '—')}",
            f"📊 Score: <b>{score_str}</b> | Tier: <b>{tier}</b>",
            f"{channel_icon} Contact: <code>{contact}</code>",
            f"⚠️ Issue: {issue}",
            f"",
            f"✉️ <b>Draft:</b> {subject}",
            f"<i>{body_preview}...</i>",
            f"",
            f"🆔 <code>{lead['id']}</code>",
        ]

    lines += [
        f"{'─' * 30}",
        f"",
        f"To send an email, reply:",
        f"<code>send [lead_id]</code>",
    ]

    _send("\n".join(lines))


def notify_simple(message: str) -> None:
    """Send a plain text notification."""
    _send(message)
