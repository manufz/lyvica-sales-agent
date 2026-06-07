"""
Poll the AgentMail inbox for new replies, classify them, update leads, and
notify Telegram. Runs every 2 hours via launchd (com.lyvica.replies).

Replaces the inbound webhook — simpler, no public URL needed, and the
inbox-scoped key can read its own inbox.
"""
import os
import re
import sys
import urllib.parse

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.db import SessionLocal
from app.models import Lead
from app.notify import send_telegram
from app.replies import process_inbound

# Senders / subjects that indicate a delivery failure (bounce), not a real reply.
_BOUNCE_FROM = ("mailer-daemon", "postmaster", "no-reply", "noreply")
_BOUNCE_SUBJECT = ("delivery status notification", "undeliverable", "undelivered",
                   "delivery has failed", "returned mail", "mail delivery failed",
                   "failure notice")


def _is_bounce(from_addr: str, subject: str, labels: list) -> bool:
    f = (from_addr or "").lower()
    s = (subject or "").lower()
    if any(b in f for b in _BOUNCE_FROM):
        return True
    if any(b in s for b in _BOUNCE_SUBJECT):
        return True
    if any("bounce" in (l or "").lower() or "failed" in (l or "").lower() for l in (labels or [])):
        return True
    return False


def _handle_bounce(db, body: str) -> str | None:
    """Find the bounced lead (its email appears in the bounce body) and either
    switch it to an alternate contact channel or mark it dead. Returns a note."""
    import re
    emails = set(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", body or ""))
    our = settings.AGENTMAIL_INBOX_ID.lower()
    for e in emails:
        if e.lower() == our:
            continue
        lead = db.query(Lead).filter(Lead.email.ilike(e)).first()
        if not lead:
            continue
        if lead.contact_form_url or lead.instagram_url:
            lead.delivery_status = "bounced"
            lead.recommended_channel = "contact_form" if lead.contact_form_url else "instagram"
            lead.outreach_status = "skipped"  # stop email attempts; manual channel
            db.commit()
            return f"⚠️ Bounced: {lead.company_name} <{e}> — switched to {lead.recommended_channel} (manual)"
        else:
            lead.delivery_status = "dead"
            lead.outreach_status = "dead"
            db.commit()
            return f"⚠️ Bounced: {lead.company_name} <{e}> — no other contact, marked dead"
    return None

# File of already-processed message ids (dedup across runs; covers replies from
# senders with no matching lead too, which wouldn't be stored in the DB).
_SEEN_FILE = os.path.expanduser("~/.lyvica_seen_replies")


def _load_seen() -> set:
    try:
        with open(_SEEN_FILE) as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()


def _mark_seen(ids: list[str]) -> None:
    if not ids:
        return
    with open(_SEEN_FILE, "a") as f:
        for i in ids:
            f.write(i + "\n")


def _email(addr: str) -> str:
    m = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", addr or "")
    return (m.group(0) if m else addr or "").lower()


def main() -> int:
    if not settings.AGENTMAIL_API_KEY or not settings.AGENTMAIL_INBOX_ID:
        print("AgentMail not configured", file=sys.stderr)
        return 1

    base = settings.AGENTMAIL_BASE_URL.rstrip("/")
    inbox = urllib.parse.quote(settings.AGENTMAIL_INBOX_ID)
    headers = {"Authorization": f"Bearer {settings.AGENTMAIL_API_KEY}"}
    our_addr = settings.AGENTMAIL_INBOX_ID.lower()

    try:
        r = httpx.get(f"{base}/inboxes/{inbox}/messages?limit=50", headers=headers, timeout=30)
        r.raise_for_status()
        messages = r.json().get("messages", [])
    except Exception as exc:
        print(f"list failed: {exc}", file=sys.stderr)
        return 1

    seen = _load_seen()
    db = SessionLocal()
    new_replies = []
    bounces = []
    newly_seen = []

    for m in messages:
        labels = m.get("labels") or []
        mid = m.get("message_id")
        subject = m.get("subject")
        from_addr = _email(m.get("from", ""))

        # Skip our own outbound, already-processed, and anything from our address
        if "sent" in labels or from_addr == our_addr or not mid or mid in seen:
            continue

        # Fetch full body (list only returns a preview)
        body = m.get("preview", "") or ""
        try:
            gr = httpx.get(f"{base}/inboxes/{inbox}/messages/{urllib.parse.quote(mid)}",
                           headers=headers, timeout=30)
            if gr.status_code == 200:
                body = gr.json().get("text") or body
        except Exception:
            pass

        # Bounce? Handle delivery failure instead of treating it as a reply.
        if _is_bounce(from_addr, subject, labels):
            note = _handle_bounce(db, body)
            if note:
                bounces.append(note)
            newly_seen.append(mid)
            continue

        res = process_inbound(db, from_addr, subject, body, mid)
        new_replies.append((from_addr, subject, res))
        newly_seen.append(mid)

    db.close()
    _mark_seen(newly_seen)

    if new_replies:
        lines = [f"📬 {len(new_replies)} new repl{'y' if len(new_replies) == 1 else 'ies'}:"]
        for frm, subj, res in new_replies:
            lead = res["lead"]
            who = f"{lead.company_name} ({frm})" if lead else f"{frm} (no matching lead)"
            lines.append(f"\n📨 {who}\n🏷️ {res['classification']} → {res['action']}\n✉️ {subj or '(no subject)'}")
            if lead:
                lines.append(f"🆔 {lead.id}")
        lines.append("\nAct on these in the group.")
        send_telegram("\n".join(lines))

    if bounces:
        send_telegram("📭 Delivery issues:\n" + "\n".join(bounces))

    print(f"checked {len(messages)} messages, {len(new_replies)} replies, {len(bounces)} bounces")
    return 0


if __name__ == "__main__":
    sys.exit(main())
