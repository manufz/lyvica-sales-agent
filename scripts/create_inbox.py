"""
Create the AgentMail inbox the agent sends from, then print its id.
Put the printed id into .env as AGENTMAIL_INBOX_ID so it's reused.

Usage:  python scripts/create_inbox.py
Requires AGENTMAIL_API_KEY in .env.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agentmail import create_inbox
from app.config import settings

if not settings.AGENTMAIL_API_KEY:
    print("AGENTMAIL_API_KEY not set in .env", file=sys.stderr)
    sys.exit(1)

data = create_inbox(
    username=settings.AGENTMAIL_USERNAME or None,
    domain=settings.AGENTMAIL_DOMAIN or None,
    display_name=settings.AGENTMAIL_DISPLAY_NAME or None,
)
inbox_id = data.get("inbox_id") or data.get("id") or data.get("address")
print("Inbox created.")
print("  inbox_id / address:", inbox_id)
print("  full response:", data)
print("\nAdd this to .env:")
print(f"AGENTMAIL_INBOX_ID={inbox_id}")
