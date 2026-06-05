"""Run as a cron job to process due follow-ups.

Suggested cron (hourly):
    0 * * * * cd /path/to/lyvica-sales-agent && .venv/bin/python scripts/run_due_followups.py >> logs/followups.log 2>&1
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import SessionLocal
from app.followups import send_due_followups

db = SessionLocal()
try:
    summary = send_due_followups(db)
    print(f"processed={summary.processed} sent={summary.sent} skipped={summary.skipped}")
    for err in summary.errors:
        print(f"ERROR: {err}", file=sys.stderr)
finally:
    db.close()
