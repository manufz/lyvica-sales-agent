import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def send_email(to: str, subject: str, body: str) -> dict:
    if not settings.RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not configured")

    payload = {
        "from": settings.FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "text": body,
    }

    with httpx.Client(timeout=15) as client:
        r = client.post(
            _RESEND_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        )
        r.raise_for_status()
        data = r.json()
        log.info("email sent to %s, provider id: %s", to, data.get("id"))
        return data
