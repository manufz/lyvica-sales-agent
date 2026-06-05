# lyvica-sales-agent

FastAPI backend that handles deterministic sales operations for the Lyvica outbound workflow.
Hermes (DeepSeek v4 Pro) is the orchestrator/writer; this service is the reliable backend for state, sending, and scheduling.

## Architecture

```
Hermes (AI brain) ──► lyvica-sales-agent (this repo, port 9000)
                              │
                    ┌─────────┼─────────────┐
                    ▼         ▼             ▼
             lyvica-scoring  Postgres     Resend / Stripe
             (port 8000)
```

## Setup

### 1. Start Postgres
```bash
docker compose up -d
```

### 2. Create virtualenv
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env and fill in RESEND_API_KEY, STRIPE_SECRET_KEY, etc.
```

### 5. Initialize database
```bash
python scripts/init_db.py
```

### 6. Start lyvica-scoring (separate terminal)
```bash
cd ../lyvica-scoring
source .venv/bin/activate
uvicorn web.main:app --reload --port 8000
```

### 7. Start this service
```bash
cd ../lyvica-sales-agent
source .venv/bin/activate
uvicorn app.main:app --reload --port 9000
```

---

## API Quick Reference

All write endpoints require header: `x-hermes-secret: <value>`

### Health
```bash
curl http://localhost:9000/health
```

### Research a lead
```bash
curl -X POST http://localhost:9000/leads/research \
  -H "Content-Type: application/json" \
  -H "x-hermes-secret: change-this" \
  -d '{
    "company_name": "Example Dental",
    "website_url": "https://example.com",
    "city": "Vienna",
    "country": "Austria",
    "industry": "dentist"
  }'
```

### Draft initial outreach
```bash
curl -X POST http://localhost:9000/leads/{lead_id}/draft-initial \
  -H "x-hermes-secret: change-this"
```

### Send initial email
```bash
curl -X POST http://localhost:9000/leads/{lead_id}/send-initial \
  -H "x-hermes-secret: change-this"
```

### List due follow-ups
```bash
curl http://localhost:9000/followups/due
```

### Send due follow-ups
```bash
curl -X POST http://localhost:9000/followups/send-due \
  -H "x-hermes-secret: change-this"
```

### Classify a reply
```bash
curl -X POST http://localhost:9000/replies/classify \
  -H "Content-Type: application/json" \
  -H "x-hermes-secret: change-this" \
  -d '{
    "lead_id": "...",
    "from_email": "owner@example.com",
    "body": "Yes, please send the snapshot!"
  }'
```

### Create Stripe payment link
```bash
curl -X POST http://localhost:9000/stripe/checkout-link \
  -H "Content-Type: application/json" \
  -H "x-hermes-secret: change-this" \
  -d '{
    "lead_id": "...",
    "package": "starter",
    "buying_intent": true
  }'
```

---

## Follow-up Cron Job

```bash
# Run hourly
0 * * * * cd /path/to/lyvica-sales-agent && .venv/bin/python scripts/run_due_followups.py >> logs/followups.log 2>&1
```

---

## Tests

```bash
pytest tests/ -v
```

---

## Hermes Integration

Load `prompts/hermes_skill.md` as a skill in Hermes. Hermes handles all reasoning, writing, and decision-making. This backend handles all state, sending, and scheduling.

## Outreach Guardrails

- Hermes does **not** send emails autonomously — Manuel must confirm.
- Instagram DMs: discovery only, copy generated for Manuel to send manually.
- Contact forms: URL discovered, message drafted, Manuel submits manually.
- Stripe links: only generated on explicit `buying_intent: true` — never in first outreach.
- One follow-up maximum unless Manuel explicitly requests more.
