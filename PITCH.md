# LYVICA — Hackathon Pitch

**Tagline:** Find. Build. Pitch. Automatically.
**One-liner:** An autonomous agent that finds local businesses with bad websites,
rebuilds them, and emails the owner a working new site — end to end.

---

## 1. The Problem
- Millions of small businesses run outdated, non-mobile, slow, or insecure websites.
- They lose customers to competitors — but don't know it, and don't have time to fix it.
- For an agency, the work is brutal manual labor: find prospects → judge their site →
  build a sample → find the contact → write the pitch → send → follow up → handle replies.
- Nobody does all of that at scale. It's the perfect job for an agent.

## 2. The Solution — one closed loop
**Lyvica runs the entire outbound motion autonomously:**
`Source → Score → Build → Pitch → Send → Reply` — surfaced to a human in Telegram for one-tap control.
The payoff line: **a working new website in the owner's inbox — not a mockup, not a sales call.**

## 3. How it works (the loop)
1. **Source** — pulls local businesses by city × sector from Google Places (paginated, deduped).
2. **Score** — rates each site's "rebuild opportunity" (0–100): mobile speed, visual datedness
   (vision model on a live screenshot), HTTPS, content age, tech stack, + a DIY-builder "easy-sell" signal.
3. **Surface** — the best leads land in a Telegram group every morning, with scores + the exact issue.
4. **Build** — the owner-facing builder at lyvica.com generates a modern site for the flagged business.
5. **Pitch** — an LLM writes a tailored, compliant cold email referencing the real issue + the new site link.
6. **Send** — human approves in chat; email goes out via the agent's own inbox, rate-limited + business-hours-safe.
7. **Reply** — inbound replies are auto-classified (interested / asks price / not interested / …) and surfaced.

## 4. Architecture
```
  Telegram group ⇄ Hermes Agent (Nous Research)      ← brain + operator UI
        │  MCP tools (stdio)
        ▼
  lyvica-sales-agent  (FastAPI)                       ← state, sending, scheduling
   ├─ scoring (in-process): signals + vision
   ├─ sourcing: Google Places + PageSpeed
   ├─ outreach: LLM writer + compliance footer
   ├─ email: AgentMail (send + receive)
   ├─ CRM: SQLite (leads, messages, market coverage)
   └─ Stripe: payment links
        ▲
  LLMs via TrueFoundry Virtual Model Groups on Amazon Bedrock
```
- **Deterministic backend** does the reliable work; **Hermes** does reasoning, conversation, and orchestration.
- **MCP server** exposes Lyvica's actions as typed tools the agent calls (no brittle prompt-glue).
- Runs 24/7 on a Mac via `launchd`: twice-daily lead sweeps, outbox sender, reply poller.

## 5. Sponsor tech (and why)
- **TrueFoundry** — every LLM call goes through the gateway as a **Virtual Model Group** with a
  fallback chain (Claude Sonnet 4.6 → Qwen → DeepSeek/Pixtral). Resilience + hot-swap + observability,
  no code changes. Two groups: `lyvica-agent` (chat/tools) and `lyvica-vision` (website scoring).
- **Amazon Bedrock** — the underlying models (Qwen3-VL 235B for vision, Claude Sonnet 4.6, etc.).
- **Hermes Agent (Nous Research)** — the autonomous agent + Telegram gateway + skill/memory system.
- **AgentMail** — gives the agent a real inbox (`lyvica@agentmail.to`) that sends AND receives,
  so the reply loop actually closes — something a normal transactional email API can't do.

## 6. The "magic" — scoring quality
- Vision LLM judges *how dated a site looks* from a screenshot — the signal that actually predicts
  "owner will be embarrassed enough to act." Returns the datedness score + the specific visible problem
  + a tailored pitch in one call.
- A **confidence gate** refuses to score on too few signals (no garbage leads).
- A **DIY-builder detector** (Wix/Squarespace/GoDaddy…) flags low-attachment, easy-sell owners —
  a buying-intent signal, distinct from "site is ugly."

## 7. Trust & safety (production-minded)
- Human-in-the-loop: nothing sends without approval in Telegram.
- Warm-up ramp (3→10/day) + business-hours window + daily cap → deliverability-safe.
- Compliance footer (identity, opt-out) on every email; opt-outs honored automatically.
- Bounce handling: switch channel or mark dead; one follow-up max; reply-race guarded.

## 8. Live demo
- Real leads, scored live: **Bronco Electric (67)**, **Honeycomb Salon (62)** — genuinely dated sites.
- Lyvica built each a free preview site → emailed the owner the **live link** → both visible in Telegram
  (lead card + "outreach sent") and in the inbox's Sent folder.
- The eureka: **old site vs. new site**, and **a working site already sitting in their inbox.**

## 9. Why it's different
- Not a chatbot, not a "lead list" tool — it's the **whole loop**, autonomous, with a human just approving.
- Most outreach tools send mockups or ask for a call. Lyvica sends a **finished, working website.**
- Built on a real agent (Hermes) + governed model infra (TrueFoundry/Bedrock), not a one-off script.

## 10. What's real (today)
- End-to-end working: sourcing, vision scoring, market rotation, LLM outreach, real sending + receiving,
  reply classification, Telegram control — all live on a server, 24/7.

## 11. Cost
- Negligible per lead (~$0.01 vision + ~$0.01 email-writing); free tiers for Places/PageSpeed/AgentMail.
- Virtual Model Groups let us route to the cheapest capable model and fall back only when needed.

## 12. Roadmap
- Auto-handoff scorer → builder (one prompt-free rebuild).
- Outcome-based scoring: learn which markets/signals actually convert from real reply rates.
- Own sending domain + multi-channel (form/Instagram), A/B subject lines, CRM dashboard.

---
**Lyvica — Find. Build. Pitch. Automatically.**  ·  lyvica.com
