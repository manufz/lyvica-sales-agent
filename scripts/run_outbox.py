"""
Outbox runner — launchd com.lyvica.outbox, every ~20 min.

1. Refresh inbound replies first (reply-race fix: a lead who just replied
   won't get a follow-up).
2. Send due follow-ups + approved initials, under business-hours + daily cap.
3. Post a short Telegram summary of what went out.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal
from app.notify import send_telegram
from app.outbox import run_outbox


def main() -> int:
    # 1. Refresh replies first so follow-ups never race a fresh reply.
    try:
        import scripts.check_replies as check_replies
        check_replies.main()
    except Exception as exc:
        print(f"reply refresh failed (continuing): {exc}", file=sys.stderr)

    # 2. Send under the window + cap.
    db = SessionLocal()
    try:
        summary = run_outbox(db)
    finally:
        db.close()

    print(summary)

    # 3. Notify only when something actually went out (avoid noise every 20 min).
    sent_i = summary.get("initials_sent", [])
    sent_f = summary.get("followups_sent", [])
    if sent_i or sent_f:
        lines = ["📤 Outbox sent:"]
        if sent_i:
            lines.append(f"\n✉️ {len(sent_i)} initial:")
            lines += [f"  • {x}" for x in sent_i]
        if sent_f:
            lines.append(f"\n🔁 {len(sent_f)} follow-up:")
            lines += [f"  • {x}" for x in sent_f]
        lines.append(f"\nRemaining today: {summary.get('remaining_after', 0)}")
        send_telegram("\n".join(lines))

    for err in summary.get("errors", []):
        print(f"ERROR: {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
