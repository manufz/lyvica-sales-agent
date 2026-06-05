"""
Lyvica local MCP server (stdio).

Exposes the lyvica-sales-agent REST API as typed MCP tools so Hermes (or any
MCP client) calls structured tools instead of hand-writing curl commands.
Runs as a stdio subprocess spawned by Hermes — no extra port or service.

Register with Hermes:
    hermes mcp add lyvica \
      --command /Users/macpro/work/lyvica-sales-agent/.venv/bin/python \
      --args /Users/macpro/work/lyvica-sales-agent/mcp_server.py
"""
from __future__ import annotations

import os
import subprocess

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

_REPO = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_REPO, ".env"))

BASE = os.environ.get("APP_BASE_URL", "http://localhost:9000").rstrip("/")
SECRET = os.environ.get("HERMES_SHARED_SECRET", "change-this")
HEADERS = {"x-hermes-secret": SECRET}
LAUNCH = os.path.join(_REPO, "scripts", "launch_pipeline.sh")

mcp = FastMCP("lyvica")


def _get(path: str, timeout: float = 30) -> dict:
    with httpx.Client(timeout=timeout) as c:
        r = c.get(f"{BASE}{path}", headers=HEADERS)
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict | None = None, timeout: float = 120) -> dict:
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{BASE}{path}", headers=HEADERS, json=body or {})
        r.raise_for_status()
        return r.json()


# ── Lead sourcing (fire-and-forget — the pipeline takes minutes) ───────────────

@mcp.tool()
def find_leads(city: str = "", sector: str = "") -> str:
    """
    Search for outdated-website business leads and post the qualifying ones to
    Telegram. Use for any "find/look for customers/leads in <city> <sector>" request.

    Pass city + sector for a specific market (e.g. city="Bakersfield", sector="electrician").
    Leave BOTH blank to auto-select the next best market by past yield.

    Returns immediately; results arrive in Telegram in a few minutes. Do not wait
    or poll after calling this — just tell the user it's running.
    """
    args = ["bash", LAUNCH]
    if city and sector:
        args += [city, sector]
    out = subprocess.run(args, capture_output=True, text=True, timeout=20)
    return (out.stdout or out.stderr or "pipeline launched").strip()


@mcp.tool()
def sweep(count: int = 3) -> str:
    """
    Proactively prospect ACROSS several different areas/sectors in one run.
    Sources, scores, contacts, and drafts for `count` markets spread across
    different cities, then posts a combined digest to Telegram. Use when asked to
    "find leads across areas", "prospect broadly", or "get me a batch of leads".
    Returns immediately; results arrive in Telegram in a few minutes.
    """
    py = os.path.join(_REPO, ".venv", "bin", "python")
    script = os.path.join(_REPO, "scripts", "run_pipeline.py")
    log = os.path.expanduser("~/logs/pipeline.log")
    with open(log, "a") as lf:
        subprocess.Popen([py, script, "--sweep", str(count)],
                         stdout=lf, stderr=lf, start_new_session=True)
    return f"Started a {count}-area sweep — qualifying leads will post to Telegram shortly."


@mcp.tool()
def market_stats() -> dict:
    """
    Return the lead-yield table across every city × sector market, plus the
    recommended next market to work. Use to decide where the best leads are or
    answer "what should we work next?". Each market shows runs, sourced,
    qualified, yield, and whether it's exhausted.
    """
    return _get("/markets/stats")


# ── Single-lead operations ─────────────────────────────────────────────────────

@mcp.tool()
def research_lead(company_name: str, website_url: str,
                  city: str = "", industry: str = "") -> dict:
    """
    Research and score ONE business by URL: discovers contacts, scores the site
    (mobile, visual datedness, security, DIY-builder buying signal), and drafts
    outreach. Takes up to ~60s. Returns the full lead record including score,
    tier, contact info, buying_signals, and the lead id.
    """
    return _post("/leads/research", {
        "company_name": company_name,
        "website_url": website_url,
        "city": city or None,
        "industry": industry or None,
    }, timeout=120)


@mcp.tool()
def send_initial(lead_id: str) -> dict:
    """
    Send the drafted initial outreach email for a lead via Resend. Only call
    after the user has explicitly approved sending to this lead_id.
    """
    return _post(f"/leads/{lead_id}/send-initial")


@mcp.tool()
def classify_reply(lead_id: str, from_email: str, body: str) -> dict:
    """
    Classify an inbound reply for a lead (interested / asks_price / asks_examples
    / ready_to_buy / not_interested / unclear) and store it. Returns the
    classification and recommended next action.
    """
    return _post("/replies/classify", {
        "lead_id": lead_id, "from_email": from_email, "body": body,
    })


@mcp.tool()
def create_payment_link(lead_id: str, package: str, buying_intent: bool) -> dict:
    """
    Create a Stripe checkout link for a lead. package is "starter" or "pro".
    buying_intent MUST be true (only call when the lead has explicitly expressed
    intent to buy). Never use in first outreach.
    """
    return _post("/stripe/checkout-link", {
        "lead_id": lead_id, "package": package, "buying_intent": buying_intent,
    })


if __name__ == "__main__":
    mcp.run()  # stdio transport
