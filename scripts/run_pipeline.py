"""
Daily pipeline script — runs outside Hermes agent loop to avoid timeout.
Called by launchd cron, sends results to Telegram via `hermes send`.

Flow:
  1. Call POST /leads/pipeline  (long-running: contact discovery + scoring)
  2. Format a plain-text summary with all contact details
  3. Send to Telegram via: hermes send -t telegram "<summary>"
"""
import json
import subprocess
import sys
import os
from datetime import datetime, timezone

# Allow running from any working directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

HERMES_BIN = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/hermes")


def call_pipeline(city: str, industry: str, limit: int) -> dict:
    import urllib.request
    import urllib.error

    body: dict = {"limit": limit}
    # When city/industry are omitted, the API's selector picks the next market.
    if city:
        body["city"] = city
    if industry:
        body["industry"] = industry
    payload = json.dumps(body).encode()

    req = urllib.request.Request(
        f"{settings.APP_BASE_URL}/leads/pipeline",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-hermes-secret": settings.HERMES_SHARED_SECRET,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())


def call_sweep(count: int, limit: int) -> dict:
    import urllib.request

    payload = json.dumps({"count": count, "limit": limit}).encode()
    req = urllib.request.Request(
        f"{settings.APP_BASE_URL}/leads/sweep",
        data=payload,
        headers={"Content-Type": "application/json",
                 "x-hermes-secret": settings.HERMES_SHARED_SECRET},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2400) as resp:
        return json.loads(resp.read())


def _lead_block(lead: dict, idx: int) -> list[str]:
    """One actionable lead entry: name, site, score, contact, signals, issue, id."""
    score = lead.get("score")
    score_str = str(int(score)) if score is not None else "N/A"
    tier = (lead.get("tier") or "?").upper()

    # Only email leads are sendable; form/Instagram are manual.
    if lead.get("email"):
        contact = f"📧 {lead['email']}  (emailable)"
    elif lead.get("contact_form_url"):
        contact = f"📝 {lead['contact_form_url']}  (manual: submit form)"
    elif lead.get("instagram_url"):
        contact = f"📸 {lead['instagram_url']}  (manual: DM)"
    else:
        contact = "❓ no contact"

    block = [
        f"{idx}. {lead.get('company_name') or '—'}",
        f"🌐 {lead.get('website_url') or '—'}",
        f"📊 Score {score_str} | {tier}",
        contact,
    ]
    for sig in (lead.get("buying_signals") or []):
        block.append(f"🎯 {sig}")
    block += [
        f"⚠️ {lead.get('primary_issue') or 'website improvements needed'}",
        f"🆔 {lead['id']}",
        "",
    ]
    return block


_CMD_BAR = (
    "Commands:  draft <id> (preview)  ·  send <id> (queue)  ·  "
    "edit <id> <change>  ·  skip <id>  ·  send all"
)


def format_summary(data: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%b %d %Y %H:%M UTC")
    lines = [
        f"🎯 Lyvica — {data['industry'].title()} in {data['city']}",
        f"📅 {now}",
        f"📊 {data['total_sourced']} sourced → {data['qualifying']} qualifying "
        f"(skipped {data['skipped_no_contact']} no-contact, {data['skipped_low_score']} low-score)",
        "",
    ]
    for i, lead in enumerate(data["leads"], 1):
        lines += _lead_block(lead, i)
    lines.append(_CMD_BAR)
    return "\n".join(lines)


def format_sweep(data: dict) -> str:
    """Grouped, actionable digest across multiple areas."""
    now = datetime.now(timezone.utc).strftime("%b %d %Y %H:%M UTC")
    lines = [
        f"🧭 Lyvica Sweep — {data['markets_worked']} areas",
        f"📅 {now}",
        f"📊 {data['total_qualifying']} qualifying leads from "
        f"{data['total_sourced']} sourced across {data['markets_worked']} markets",
    ]
    # Per-area headline counts first (the scannable summary)
    for m in data["markets"]:
        lines.append(f"  • {m['industry'].title()} in {m['city']}: "
                     f"{m['qualifying']} qualifying / {m['total_sourced']} sourced")
    lines.append("")

    # Then the actionable detail, grouped by area
    n = 0
    for m in data["markets"]:
        if not m["leads"]:
            continue
        lines.append(f"━━━ {m['industry'].title()} · {m['city']} ━━━")
        for lead in m["leads"]:
            n += 1
            lines += _lead_block(lead, n)

    lines.append(_CMD_BAR)
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    """Send to Telegram, splitting long digests into <=3500-char chunks."""
    if not os.path.exists(HERMES_BIN):
        print(f"hermes not found at {HERMES_BIN}", file=sys.stderr)
        return False
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or settings.TELEGRAM_CHAT_ID
    target = f"telegram:{chat_id}" if chat_id else "telegram"

    # Chunk on line boundaries to stay under Telegram's 4096-char message limit
    chunks: list[str] = []
    cur = ""
    for line in message.split("\n"):
        if len(cur) + len(line) + 1 > 3500:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)

    ok = True
    for chunk in chunks:
        result = subprocess.run([HERMES_BIN, "send", "-t", target, chunk],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"hermes send failed: {result.stderr}", file=sys.stderr)
            ok = False
        else:
            print(result.stdout.strip())
    return ok


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Lyvica lead pipeline / sweep and post to Telegram.")
    parser.add_argument("--city", default=None)
    parser.add_argument("--industry", default=None)
    parser.add_argument("--limit", type=int, default=settings.PIPELINE_DEFAULT_LIMIT)
    parser.add_argument("--sweep", type=int, default=0,
                        help="Work N markets across different areas in one run.")
    args = parser.parse_args()

    try:
        if args.sweep and args.sweep > 0:
            print(f"Running sweep: {args.sweep} markets x {args.limit} leads...")
            data = call_sweep(args.sweep, args.limit)
            print(f"  markets={data['markets_worked']} qualifying={data['total_qualifying']}")
            digest = format_sweep(data)
        else:
            target = f"{args.industry} in {args.city}" if (args.city and args.industry) \
                else "auto-selected market (by yield)"
            print(f"Running pipeline: {args.limit} leads — {target}...")
            data = call_pipeline(args.city, args.industry, args.limit)
            print(f"  sourced={data['total_sourced']} qualifying={data['qualifying']}")
            digest = format_summary(data)
    except Exception as exc:
        msg = f"❌ Lyvica run failed: {exc}"
        print(msg, file=sys.stderr)
        send_telegram(msg)
        sys.exit(1)

    print(digest)
    sys.exit(0 if send_telegram(digest) else 1)
