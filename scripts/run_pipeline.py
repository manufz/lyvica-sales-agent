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

    payload = json.dumps({
        "city": city,
        "industry": industry,
        "limit": limit,
    }).encode()

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


def format_summary(data: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%b %d %Y %H:%M UTC")
    city = data["city"]
    industry = data["industry"].title()
    lines = [
        f"🎯 Lyvica Pipeline — {industry} in {city}",
        f"📅 {now}",
        f"",
        f"📊 {data['total_sourced']} sourced → {data['qualifying']} qualifying"
        f"  (skipped: {data['skipped_no_contact']} no contact, "
        f"{data['skipped_low_score']} low score)",
    ]

    for i, lead in enumerate(data["leads"], 1):
        score = lead.get("score")
        tier = (lead.get("tier") or "?").upper()
        score_str = str(int(score)) if score is not None else "N/A"

        # Actual contact detail — not just the channel name
        email = lead.get("email")
        form = lead.get("contact_form_url")
        ig = lead.get("instagram_url")

        if email:
            contact_line = f"📧 {email}"
        elif form:
            contact_line = f"📝 {form}"
        elif ig:
            contact_line = f"📸 {ig}"
        else:
            contact_line = "❓ no contact"

        issue = lead.get("primary_issue") or "website improvements needed"
        subject = lead.get("first_subject") or "—"
        website = lead.get("website_url") or "—"
        name = lead.get("company_name") or "—"

        block = [
            f"",
            f"{'─'*28}",
            f"{i}. {name}",
            f"🌐 {website}",
            f"📊 Score: {score_str} | Tier: {tier}",
            contact_line,
        ]
        # Buying signals (e.g. DIY builder) — prominent, they predict conversion
        for sig in (lead.get("buying_signals") or []):
            block.append(f"🎯 {sig}")
        block += [
            f"⚠️  {issue}",
            f"✉️  {subject}",
            f"🆔 {lead['id']}",
        ]
        lines += block

    lines += [
        f"",
        f"{'─'*28}",
        f"Reply 'send [id]' to approve outreach.",
    ]
    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    if not os.path.exists(HERMES_BIN):
        print(f"hermes not found at {HERMES_BIN}", file=sys.stderr)
        return False

    # Use TELEGRAM_CHAT_ID from env if set, otherwise fall back to home channel
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or settings.TELEGRAM_CHAT_ID
    target = f"telegram:{chat_id}" if chat_id else "telegram"

    result = subprocess.run(
        [HERMES_BIN, "send", "-t", target, message],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"hermes send failed: {result.stderr}", file=sys.stderr)
        return False
    print(result.stdout.strip())
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Lyvica lead pipeline and post to Telegram.")
    parser.add_argument("--city", default=settings.PIPELINE_DEFAULT_CITY)
    parser.add_argument("--industry", default=settings.PIPELINE_DEFAULT_INDUSTRY)
    parser.add_argument("--limit", type=int, default=settings.PIPELINE_DEFAULT_LIMIT)
    args = parser.parse_args()

    city = args.city
    industry = args.industry
    limit = args.limit

    print(f"Running pipeline: {limit} {industry} in {city}...")
    try:
        data = call_pipeline(city, industry, limit)
    except Exception as exc:
        msg = f"❌ Lyvica pipeline failed: {exc}"
        print(msg, file=sys.stderr)
        send_telegram(msg)
        sys.exit(1)

    print(f"  sourced={data['total_sourced']} qualifying={data['qualifying']}")
    summary = format_summary(data)
    print(summary)

    sent = send_telegram(summary)
    sys.exit(0 if sent else 1)
