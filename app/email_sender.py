"""
Outbound email — provider-dispatching front door.

Everything in the app calls `send_email(to, subject, body)`. This routes to:
  - AgentMail  if AGENTMAIL_API_KEY is set   (agent inbox: send + receive)
  - Resend     elif RESEND_API_KEY is set    (legacy fallback)
  - else fails clearly.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def _send_resend(to: str, subject: str, body: str) -> dict:
    payload = {"from": settings.FROM_EMAIL, "to": [to], "subject": subject, "text": body}
    with httpx.Client(timeout=15) as client:
        r = client.post(_RESEND_URL, json=payload,
                        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"})
        r.raise_for_status()
        data = r.json()
    log.info("Resend email sent to %s, id: %s", to, data.get("id"))
    return data


def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via the configured provider. Raises clearly if none configured."""
    if settings.AGENTMAIL_API_KEY:
        from app.agentmail import send_email as _agentmail_send
        return _agentmail_send(to, subject, body)
    if settings.RESEND_API_KEY:
        return _send_resend(to, subject, body)
    raise RuntimeError("No email provider configured — set AGENTMAIL_API_KEY or RESEND_API_KEY")
