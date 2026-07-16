# 🔧 Plumber Missed-Call → SMS Agent

> **Status: build shipped, go-to-market killed.** After two customer-discovery
> conversations and a competitor scan I should have run in week zero, I learned
> this has been a product since ~2014 (Podium), a $97/mo commodity since 2021
> (GoHighLevel), and a checkbox in the platforms plumbers already pay for
> (Housecall Pro & co). The full post-mortem — and what I'm keeping from it —
> is in **[ARTICLE.md](ARTICLE.md)**. The engineering below stands on its own.

A missed-call text-back agent for a solo/small plumbing company. A real phone
number rings; if the plumber doesn't pick up (he's under a sink), the caller gets
a text within seconds, a small agent collects the job over SMS — issue, address,
name, preferred time, photos — and the plumber gets one clean summary he can call
back on, ready to quote. Every missed call logs a **value receipt**.

> The value is the $300–3,000 job that would otherwise have hit voicemail and
> gone to the next result on Google.

Sibling of a real-time voice agent I built for an auto detailing studio — same
architecture (deterministic guards → one structured LLM call → owner handoff →
value receipts), swapped from voice to SMS. SMS is the right medium here: no
sub-1.5 s latency budget, ~10× cheaper per conversation, and callers *expect* a
text from a busy tradesman.

---

## What it does

- 📵 **Missed call** → instant text-back ("sorry, on a job — what's going on?").
- 💬 **Collects the job** over SMS: issue, address, name, preferred time. One
  question per text. Photos (MMS) acknowledged and counted.
- 🚨 **Escalates** emergencies, angry customers, and anything beyond intake —
  the owner is notified immediately with the full conversation.
- 🧾 **Logs a value receipt** per missed call: outcome + estimated recovered
  revenue (job value × owner's close rate). `GET /rollup` is the owner scoreboard.

### Hard boundaries (enforced in code, not just prompt)
Never quotes a price · never promises an arrival time · never gives DIY
instructions on gas/electrical/sewer · never asks for the phone number (SMS
already has it) · gas-leak / CO texts get a **verbatim, deterministic** safety
line ("leave now, call 911 / PG&E") — that reply never depends on the LLM.

---

## Architecture

```
      caller dials the Twilio number
                  │
            ┌─────▼─────┐  OWNER_FORWARD_NUMBER set?
            │  /voice   │──yes──► <Dial> owner's cell (20s) ──► /missed
            └─────┬─────┘                                          │
              no (demo)                              answered? ────┤
                  │                                       no       │
                  ▼                                                ▼
        text-back SMS fired  ◄─────────────────────────────────────┘
                  │
            caller replies
                  │
            ┌─────▼─────┐   guard (emergency / injection, 0ms, no LLM)
            │   /sms    │──► one Haiku 4.5 call → {decision, captured, reply}
            └─────┬─────┘
       CONTINUE   │   DONE / ESCALATE
     (next field) │        │
                  ▼        ▼
             reply SMS   owner handoff (SMS + email + webhook, always local jsonl)
                  │        │
                  └──► value receipt (receipts.jsonl → /rollup)
```

One inbound text → **one** Haiku call that returns the decision *and* the reply
together (no separate classify + generate round trip).

The contract:

```json
{
  "decision": "CONTINUE | DONE | ESCALATE",
  "intent": "new_job | reschedule | price_question | emergency | complaint | other",
  "reason": "one sentence, logged verbatim",
  "captured": { "name": null, "address": null, "issue": null,
                "urgency": null, "preferred_time": null, "photo_count": 0 },
  "reply_text": "the SMS to send"
}
```

---

## Security

- 🔐 **Webhook signatures** — `/voice`, `/missed`, `/sms` verify
  `X-Twilio-Signature` once `TWILIO_AUTH_TOKEN` is set (`PUBLIC_BASE_URL` makes
  this work behind ngrok).
- 🔐 **Untrusted input** — the SMS body is data, never instructions: regex
  injection gate before the LLM, delimited-as-data in the prompt, and the agent
  has **no tools**, so a hostile text's blast radius is a weird reply, never an action.
- 🔐 **Token burn cap** — 12 customer turns max per conversation, then a polite
  close + owner handoff. Twilio webhook retries are deduped by `MessageSid`.
- 🔐 **PII at rest** — `receipts.jsonl` / `messages.jsonl` / `conversations.jsonl`
  (phones, addresses, transcripts) are gitignored, never committed.
- 🔁 **Graceful failure** — if the LLM path throws mid-conversation, the caller
  gets a human-sounding fallback and the owner gets the raw message. A lead is
  never silently dropped.

---

## Quickstart

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt
python -m app.agent && python -m app.state && python -m app.notify && python -m app.receipt  # self-checks
pytest                          # hermetic — no keys, no network, no repo writes
cp .env.example .env            # fill in Twilio + Anthropic for the live demo
uvicorn app.main:app --port 5060
ngrok http 5060                 # Twilio number → Voice webhook /voice, Messaging webhook /sms
```

Full Twilio walkthrough (number, webhooks, A2P registration) in **[SETUP.md](SETUP.md)**.

## The pitch script (preserved from before the post-mortem)

1. Hand the plumber your phone: **"call this number."** It rings out — like his
   number does when he's under a sink.
2. Their phone (or yours) buzzes: the text-back arrives while you're still talking.
3. Reply as a customer: "water heater leaking, 212 Ocean St." Watch the agent
   collect the rest, one question at a time.
4. Show `GET /rollup`: *"every missed call becomes this number — estimated
   revenue recovered. Two-week free pilot on your real number, then $X one-time,
   everything runs on your own accounts."*

Personalize per pitch by flipping two env vars: `BUSINESS_NAME`, `OWNER_NAME`.

## Running costs (per client, their accounts)

| Item | Cost |
|---|---|
| Twilio number | ~$1.15/mo |
| SMS | ~$0.008/segment — a 6-text conversation ≈ $0.05 |
| Haiku 4.5 | ~$0.003/turn → ~$0.02/conversation |
| **A busy month (60 missed calls)** | **≈ $5** |

## Repo layout

```
app/
  main.py     FastAPI webhooks · signature auth · turn cap · retry dedupe · fallback
  agent.py    deterministic guards (emergency, injection) + single Haiku structured call
  state.py    conversation state (in-memory + JSONL audit)
  notify.py   owner handoff: SMS + email + webhook, always persisted locally
  receipt.py  value receipts + business rollup (/rollup)
tests/        hermetic pytest — money/safety paths offline, zero keys
evals/        12 live behavioral cases vs production prompt (~$0.02/run)
SETUP.md · TRADEOFFS.md · .env.example
```

## Tests & evals

```bash
pytest                        # deterministic code paths, free, offline
python evals/run_evals.py     # LIVE model behavior vs the production prompt (needs key)
python evals/run_evals.py --trials 3   # stability read
```

`pytest` covers what must never regress: the gas/CO gate fires without an API
key, malformed model replies re-ask instead of paging the owner, receipts don't
double-count, a dead LLM never drops a lead. `evals/` grades the live model on
the behavioral contract: never quotes a price, one question per text, never
re-asks an answered field, escalates anger, refuses DIY gas advice.
