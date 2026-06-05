# lyvica-sales-agent

A self-running outbound lead engine for finding local businesses with outdated
websites and turning them into qualified, contactable sales leads.

It **sources** businesses (Google Places), **discovers** their contacts,
**scores** their websites (PageSpeed + an LLM vision judgment of how dated they
look), **drafts** tailored outreach, and **posts** the qualifying leads to
Telegram — rotating across a whole market over time. A FastAPI backend does all
the deterministic work; **Hermes Agent** drives it conversationally via a local
**MCP server**.

## Architecture

```
        Telegram group  ◄──────────────┐  (lead summaries, you give commands)
              │                         │
              ▼                         │
        Hermes Agent  ── MCP tools ──►  mcp_server.py (stdio)
        (Qwen3 via TrueFoundry)             │  calls
                                            ▼
                            lyvica-sales-agent  (FastAPI :9000)
                                            │
              ┌──────────────┬──────────────┼───────────────┬───────────────┐
              ▼              ▼              ▼               ▼               ▼
          SQLite        Google Places   app/scoring/     Resend          Stripe
        (CRM: leads,    (sourcing +     (in-process:     (email)         (links)
         messages,       PageSpeed)      signals+vision)
         coverage)
```

Everything runs on one machine. Scoring is **in-process** (no separate service).
The CRM is **SQLite** (no Postgres). The LLMs are served through the
**TrueFoundry** OpenAI-compatible gateway:
- **Conversation/orchestration:** `qwen.qwen3-235b-a22b` (Hermes)
- **Visual datedness judgment:** `qwen.qwen3-vl-235b-a22b` (scoring)

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
| `GATEWAY_BASE_URL` / `GATEWAY_API_KEY` | TrueFoundry gateway (vision scoring) |
| `VISION_MODEL` | vision model id (default Qwen3-VL 235B) |
| `GOOGLE_PLACES_API_KEY` | lead sourcing |
| `PAGESPEED_API_KEY` | mobile performance signal |
| `HERMES_SHARED_SECRET` | auth header for all write endpoints |
| `RESEND_API_KEY` / `FROM_EMAIL` | outbound email (optional until you send) |
| `STRIPE_*` | payment links (optional) |
| `TELEGRAM_CHAT_ID` | leave blank → delivers to Hermes' home channel |
| `PIPELINE_DEFAULT_*` / `PIPELINE_MIN_SCORE` | pipeline defaults |

## API reference

All write endpoints require header `x-hermes-secret: <HERMES_SHARED_SECRET>`.

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/health` | liveness |
| POST | `/leads/pipeline` | **autonomous run** — source→score→draft (auto-selects market if none given) |
| GET  | `/markets/stats` | yield table across all markets + recommended next |
| POST | `/leads/research` | research + score ONE business |
| POST | `/leads/{id}/draft-initial` | (re)generate the first-email draft |
| POST | `/leads/{id}/send-initial` | send the drafted email via Resend |
| POST | `/email/send` | send a raw email |
| GET  | `/followups/due` | leads due a follow-up |
| POST | `/followups/send-due` | send all due follow-ups |
| POST | `/replies/classify` | classify an inbound reply |
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
(`mcp_server.py`), not curl. It exposes typed tools: `find_leads`,
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
- `com.lyvica.pipeline` — daily 9 AM auto-selected pipeline run
- `com.lyvica.followups` — hourly follow-up sender
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
