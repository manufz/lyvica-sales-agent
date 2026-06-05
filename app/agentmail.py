"""
AgentMail integration — gives the agent a real inbox that can send (and later
receive) email. Used by app.email_sender when AGENTMAIL_API_KEY is configured.

API: https://api.agentmail.to/v0
  POST /inboxes                              → create an inbox
  POST /inboxes/{inbox_id}/messages/send     → send a message
Auth: Authorization: Bearer <AGENTMAIL_API_KEY>
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Cache the resolved inbox id for the process lifetime so we don't re-create it.
_cached_inbox_id: Optional[str] = None


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.AGENTMAIL_API_KEY}"}


def _base() -> str:
    return settings.AGENTMAIL_BASE_URL.rstrip("/")


def create_inbox(username: Optional[str] = None, domain: Optional[str] = None,
                 display_name: Optional[str] = None) -> dict:
    """Create an AgentMail inbox. Returns the inbox object (incl. its id/address)."""
    if not settings.AGENTMAIL_API_KEY:
        raise RuntimeError("AGENTMAIL_API_KEY is not configured")
    body: dict = {}
    if username:
        body["username"] = username
    if domain:
        body["domain"] = domain
    if display_name:
        body["display_name"] = display_name
    with httpx.Client(timeout=20) as c:
        r = c.post(f"{_base()}/inboxes", json=body, headers=_headers())
        r.raise_for_status()
        data = r.json()
    log.info("created AgentMail inbox: %s", data.get("inbox_id") or data.get("id") or data)
    return data


def _resolve_inbox_id() -> str:
    """Return the inbox id to send from: configured id, else create one (cached)."""
    global _cached_inbox_id
    if settings.AGENTMAIL_INBOX_ID:
        return settings.AGENTMAIL_INBOX_ID
    if _cached_inbox_id:
        return _cached_inbox_id
    data = create_inbox(
        username=settings.AGENTMAIL_USERNAME or None,
        domain=settings.AGENTMAIL_DOMAIN or None,
        display_name=settings.AGENTMAIL_DISPLAY_NAME or None,
    )
    # AgentMail returns the inbox id (the address) — accept either key.
    _cached_inbox_id = data.get("inbox_id") or data.get("id") or data.get("address")
    if not _cached_inbox_id:
        raise RuntimeError(f"AgentMail inbox creation returned no id: {data}")
    log.warning("AgentMail inbox auto-created (%s). Set AGENTMAIL_INBOX_ID in .env to reuse it.",
                _cached_inbox_id)
    return _cached_inbox_id


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via AgentMail. Matches the email_sender.send_email signature."""
    if not settings.AGENTMAIL_API_KEY:
        raise RuntimeError("AGENTMAIL_API_KEY is not configured")

    inbox_id = _resolve_inbox_id()
    # Minimal HTML version improves deliverability (AgentMail recommends both).
    html = "<p>" + body.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    payload = {"to": to, "subject": subject, "text": body, "html": html}

    with httpx.Client(timeout=20) as c:
        r = c.post(f"{_base()}/inboxes/{inbox_id}/messages/send",
                   json=payload, headers=_headers())
        r.raise_for_status()
        data = r.json()
    log.info("AgentMail email sent to %s from inbox %s (msg %s)",
             to, inbox_id, data.get("message_id") or data.get("id"))
    return data
