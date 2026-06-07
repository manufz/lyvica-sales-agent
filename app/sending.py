"""
Sending controls: business-hours window + daily cap + warm-up ramp.

Every actual email send (approved initials and follow-ups) passes through
can_send_now() so volume stays safe on a cold shared-domain inbox.

Counts are derived from the messages table (outbound, direction='outbound'),
so there's no separate state to keep in sync.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Message

log = logging.getLogger(__name__)


def _now_local() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.SEND_TIMEZONE))
    except Exception:
        return datetime.now(timezone.utc)


def _start_of_local_day_utc() -> datetime:
    now = _now_local()
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(timezone.utc)


def within_window(now_local: datetime | None = None) -> bool:
    now = now_local or _now_local()
    if settings.SEND_WEEKDAYS_ONLY and now.weekday() >= 5:  # 5,6 = Sat,Sun
        return False
    return settings.SEND_WINDOW_START <= now.hour < settings.SEND_WINDOW_END


def _first_send_date_utc(db: Session) -> datetime | None:
    val = db.query(func.min(Message.sent_at)).filter(
        Message.direction == "outbound", Message.sent_at.isnot(None)
    ).scalar()
    return val


def effective_daily_cap(db: Session) -> int:
    """Warm-up ramp toward SEND_DAILY_CAP over the first days of sending."""
    cap = settings.SEND_DAILY_CAP
    if not settings.WARMUP_ENABLED:
        return cap
    first = _first_send_date_utc(db)
    if first is None:
        days = 0
    else:
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - first).days
    # ramp: day0-1 →3, day2-3 →5, day4-6 →8, day7+ →cap
    if days <= 1:
        ramp = 3
    elif days <= 3:
        ramp = 5
    elif days <= 6:
        ramp = 8
    else:
        ramp = cap
    return min(cap, ramp)


def sent_today(db: Session) -> int:
    return db.query(func.count(Message.id)).filter(
        Message.direction == "outbound",
        Message.sent_at >= _start_of_local_day_utc(),
    ).scalar() or 0


def remaining_today(db: Session) -> int:
    return max(0, effective_daily_cap(db) - sent_today(db))


def can_send_now(db: Session) -> tuple[bool, str, int]:
    """Returns (ok, reason, remaining_today)."""
    rem = remaining_today(db)
    if not within_window():
        return False, "outside business-hours window", rem
    if rem <= 0:
        return False, f"daily cap reached ({effective_daily_cap(db)})", 0
    return True, "ok", rem
