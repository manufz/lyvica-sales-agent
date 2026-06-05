"""
Minimal Telegram notifier — shells out to `hermes send`, reusing Hermes's
configured bot token (same mechanism the pipeline uses). Kept tiny on purpose;
Hermes remains the messenger.
"""
from __future__ import annotations

import logging
import os
import subprocess

from app.config import settings

log = logging.getLogger(__name__)

_HERMES_BIN = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/hermes")


def send_telegram(text: str) -> bool:
    if not os.path.exists(_HERMES_BIN):
        log.warning("hermes binary not found; cannot send Telegram notification")
        return False
    chat_id = settings.TELEGRAM_CHAT_ID
    target = f"telegram:{chat_id}" if chat_id else "telegram"
    try:
        r = subprocess.run([_HERMES_BIN, "send", "-t", target, text],
                           capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            log.error("hermes send failed: %s", r.stderr)
            return False
        return True
    except Exception as exc:
        log.error("telegram notify failed: %s", exc)
        return False
