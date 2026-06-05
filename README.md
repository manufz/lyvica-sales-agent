# lyvica-sales-agent

A self-running outbound lead engine for finding local businesses with outdated
websites and turning them into qualified, contactable sales leads.

It **sources** businesses (Google Places), **discovers** their contacts,
**scores** their websites (PageSpeed + an LLM vision judgment of how dated they
look), **drafts** tailored outreach, **sends** it via AgentMail, and **classifies
replies** automatically — sweeping across whole markets over time and posting
qualifying leads to Telegram. A FastAPI backend does all the deterministic work;
**Hermes Agent** drives it conversationally via a local **MCP server**.

## Architecture

```
        Telegram group  ◄───────────────┐  (lead digests + you give commands)
              │                          │
              ▼                          │
        Hermes Agent  ── MCP tools ──►   mcp_server.py (stdio)
        (virtual model group)                │  calls
                                             ▼
                               lyvica-sales-agent (FastAPI :9000)
   inbound replies                            │
   AgentMail inbox ◄──poll every 2h── check_replies.py
   (classify + notify)                        │
              ┌───────────┬──────────────┬────┼─────────┬─────────────┐
              ▼           ▼              ▼     ▼         ▼             ▼
          SQLite     Google Places   app/scoring/  AgentMail        Stripe
        (CRM: leads, (sourcing +     (in-process:  (send + receive  (links)
         messages,    PageSpeed)      signals +     email)
         coverage)                    vision)
```

Everything runs on one machine. Scoring is **in-process** (no separate service).
The CRM is **SQLite** (no Postgres).

**LLMs via TrueFoundry Virtual Model Groups** (fallback chains — swap models in
the console without redeploying):
- **Agent** (`lyvica-agent/virtual-agent-model`): Claude Sonnet 4.6 → Qwen3-235B → DeepSeek
- **Vision** (`lyvica-vision/virtual-vision-model`): Claude Sonnet 4.6 → Qwen3-VL 235B → Pixtral

**Email via AgentMail** (`lyvica@agentmail.to`) — sends outreach AND receives
replies. A job (`scripts/check_replies.py`) **polls the inbox every 2 hours**,
classifies new replies, matches them to leads, and pings Telegram. (Resend is
still supported as a fallback if `AGENTMAIL_API_KEY` is unset.)

## How the pipeline works

```
1. SELECT   yield-aware selector picks the next city × sector market
            (explore everything once → then exploit highest-yield markets)
2. SOURCE   Google Places text search, paginated (~60), skipping businesses
            already in the DB so each run surfaces FRESH leads
3. DISCOVER scrape homepage + key subpages for email / contact form / Instagram
            (junk-address filter; skip if no contact channel)
4. SCORE    deterministic signals (mobile PSI, HTTPS, copyright age, tech) +
            ONE vision call (screenshot → datedness + visible problems + pitch);
            DIY-builder detection adds a buying signal
5. DRAFT    template first-email per qualifying lead
6. NOTIFY   post qualifying leads to Telegram
```

A confidence gate skips leads scored from too few signals. A DIY-builder buying
signal lets a lead qualify even below the score threshold (owner-built sites are
easy sells).

## Setup (local dev)

```bash
# 1. venv + deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # required for vision screenshots

# 2. config
cp .env.example .env                  # fill in keys (see below)

# 3. database (SQLite — no Postgres needed)
python scripts/init_db.py

# 4. run the API
uvicorn app.main:app --reload --port 9000
curl http://localhost:9000/health     # {"ok": true}
```

### Required environment variables
| Var | Purpose |
|-----|---------|
| `GATEWAY_BASE_URL` / `GATEWAY_API_KEY` | TrueFoundry gateway |
| `VISION_MODEL` | vision model / virtual group (e.g. `lyvica-vision/virtual-vision-model`) |
| `GOOGLE_PLACES_API_KEY` | lead sourcing |
| `PAGESPEED_API_KEY` | mobile performance signal |
| `HERMES_SHARED_SECRET` | auth header for all write endpoints |
| `AGENTMAIL_API_KEY` | email send + receive (preferred provider) |
| `AGENTMAIL_INBOX_ID` | inbox address, e.g. `lyvica@agentmail.to` (send + polled for replies) |
| `RESEND_API_KEY` / `FROM_EMAIL` | fallback email provider (used only if no AgentMail key) |
| `STRIPE_*` | payment links (optional) |
| `TELEGRAM_CHAT_ID` | leave blank → delivers to Hermes' home channel |
| `PIPELINE_DEFAULT_*` / `PIPELINE_MIN_SCORE` | pipeline defaults |

## API reference

All write endpoints require header `x-hermes-secret: <HERMES_SHARED_SECRET>`.

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/health` | liveness |
| POST | `/leads/pipeline` | **autonomous run** — source→score→draft (auto-selects market if none given) |
| POST | `/leads/sweep` | work N markets across different cities in one run |
| GET  | `/markets/stats` | yield table across all markets + recommended next |
| POST | `/leads/research` | research + score ONE business |
| POST | `/leads/{id}/draft-initial` | (re)generate the first-email draft |
| POST | `/leads/{id}/send-initial` | send the drafted email (AgentMail) |
| POST | `/email/send` | send a raw email |
| GET  | `/followups/due` | leads due a follow-up |
| POST | `/followups/send-due` | send all due follow-ups |
| POST | `/replies/classify` | classify an inbound reply (manual, by lead_id) |
| POST | `/stripe/checkout-link` | create a payment link (buying-intent gated) |
| POST | `/leads/ingest` | bulk insert/update leads |

Example — kick off an auto-selected pipeline run:
```bash
curl -X POST http://localhost:9000/leads/pipeline \
  -H "Content-Type: application/json" -H "x-hermes-secret: change-this" \
  -d '{"limit": 10}'
```

## Hermes integration (MCP server)

Hermes talks to this backend through a local stdio **MCP server**
(`mcp_server.py`), not curl. It exposes typed tools: `find_leads`, `sweep`,
`market_stats`, `research_lead`, `send_initial`, `classify_reply`,
`create_payment_link`.

Register it once:
```bash
hermes mcp add lyvica \
  --command /path/to/lyvica-sales-agent/.venv/bin/python \
  --args /path/to/lyvica-sales-agent/mcp_server.py
```
`prompts/hermes_soul.md` is installed as Hermes' SOUL.md and tells it to use
these tools. In the Telegram group you can then say things like
*"look for electricians in Bakersfield"* or *"what market should we work next?"*.

## Market targets

`app/targets.json` defines the universe of cities × sectors the pipeline rotates
through. Edit it freely; for deeper coverage of a big metro, add its
neighborhoods as separate city entries.

## Deployment (the Mac Pro server)

Runs as `launchd` services:
- `com.lyvica.sales-agent` — the FastAPI app (always on, :9000)
- `com.lyvica.pipeline` — twice-daily area sweeps (09:00 & 15:00, 3 markets each)
- `com.lyvica.followups` — hourly follow-up sender
- `com.lyvica.replies` — polls the AgentMail inbox every 2h, classifies replies
- `ai.hermes.gateway` — Hermes gateway (Telegram + MCP)

## Tests
```bash
pytest tests/ -v
```

## Outreach guardrails
- Never sends email without explicit approval (`send [lead_id]`).
- Stripe links only on explicit `buying_intent: true` — never in first outreach.
- Instagram/contact-form: discovery + drafting only, never auto-submitted.
- Never contacts opted-out leads. Max one automated follow-up (3 days).
