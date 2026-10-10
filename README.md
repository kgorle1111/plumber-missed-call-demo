# Plumber missed-call → SMS agent

> **Status: archived October 2026. Not maintained.** I killed the idea after
> customer discovery in July 2026 showed the product already exists inside
> software plumbers pay for. The code stays up because the architecture and the
> lesson are both worth keeping. Dependencies are unpinned, so a fresh install
> may break as the SDKs move.

When a plumber can't answer his phone because he's under a sink, the caller gets
a text within seconds. A small agent collects the job over SMS: what's wrong,
the address, a name, a preferred time, photos. The plumber gets one summary he
can call back on. Every conversation leaves a value receipt so the owner can see
what the tool recovered.

I built it in July 2026 as the first product in a "pick a local vertical, find a
pain, ship a tool" exercise. Then I talked to the people I was building for.

## The problem I thought I was solving

A plumber on a job can't pick up. Industry figures put missed calls at 25 to 40%
for service businesses, and a missed call is a $300 to $3,000 job that dials the
next result on Google. A text-back that starts collecting the job before the
caller gives up looked like the obvious fix.

That reasoning is still correct. What was wrong was the assumption that nobody
had built it.

## What discovery found

I researched around 50 local business categories in Santa Cruz, ranked them by
pain-per-dollar, built this for the winner, and only then booked discovery
conversations. I didn't pitch. I asked how the work actually runs.

- The first plumber told me he already has this. It's part of Housecall Pro,
  which also runs his scheduling, invoicing and payments.
- The office manager at a second plumbing company said they pay $279 a month for
  their platform. Does missed-call handling work? "It works. It does all of
  this." What does the software still not fix? Nothing.

Then I ran the competitor scan I should have run before writing a line of code.
It took about ten minutes. Podium has sold missed-call text-back since around
2014. GoHighLevel has shipped it on by default since 2021 at $97 a month.
Housecall Pro, Jobber and ServiceTitan bundle it, and all of them now sell AI
receptionist add-ons on top. My idea was a ten-year-old product, now a checkbox
in software my prospects already trust.

What I took from it:

1. **The bundle beats the point solution.** A shop paying $279 a month wants
   fewer vendors, not a better standalone tool.
2. **No build recommendation without a dated competitor scan.** Incumbents,
   launch dates, prices, and whether the feature is already a checkbox in a
   platform the buyer pays for.
3. **Ask the office manager, and ask the right question.** Not "what hurts?" but
   "what hurts that your current software doesn't fix, and what do you pay for
   it?" The person who drives the software all day knows what it leaves undone.

The full write-up, including the same scan run against my two backup verticals
(barbershops and auto repair, both already covered), is in
[ARTICLE.md](ARTICLE.md).

## Architecture

The shape is one I reuse across builds: **deterministic safety gates → one
structured LLM call → owner handoff**, with a receipt logged at each outcome.

```
caller dials the Twilio number
        │
   POST /voice ── OWNER_FORWARD_NUMBER set? ── yes ──► <Dial> owner (20 s) ──► POST /missed
        │                                                                          │
        no (demo mode)                                           owner didn't answer
        │                                                                          │
        └────────────────────►  text-back SMS + "textback_sent" receipt  ◄─────────┘
                                          │
                                   caller replies
                                          │
                                     POST /sms
                                          │
              1. guard(): regex gates, no LLM, no network
                 gas / CO        → verbatim safety line, ESCALATE
                 burst / flood   → fixed "shut off the main" line, ESCALATE
                 injection       → fixed refusal, CONTINUE (owner not paged)
                                          │ no gate fired
              2. one Haiku 4.5 call → JSON {decision, intent, reason, captured, reply_text}
                                          │
              3. CONTINUE → reply asks for one missing field
                 DONE / ESCALATE → owner handoff (local JSONL always; SMS, email,
                                   webhook if configured) + receipt
```

**Why gates first.** A gas-leak reply shouldn't depend on a model behaving,
parsing, or even being reachable. The gate returns a fixed line in well under a
millisecond and works with no API key.

**Why one call.** The model returns the routing decision and the reply together,
so there's no classify-then-generate round trip. Malformed output re-asks the
customer instead of escalating, because a false page to the owner's phone at
6am is how a tool gets uninstalled.

**Why a human handoff instead of booking.** The agent captures; the owner
decides. It has no tools, never writes to a calendar, and only an owner quotes a
price.

The contract the model must return:

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

## What works, and the evidence

`pytest` runs 64 tests with no keys and no network. `conftest.py` scrubs every
credential from the environment, stubs out `.env` loading, and redirects all
file writes to a temp dir. CI runs the suite plus ruff, `pip-audit` and gitleaks
on every push. What those tests pin down:

- **Safety gates** fire on their listed phrasings with no API key, and stay quiet
  on appliance jobs like "can you fix a gas water heater".
- **The LLM call** only passes arguments the installed `anthropic` SDK accepts.
  This test exists because an SDK upgrade once broke every AI turn, and
  `main.py` quietly turned each failure into an owner page.
- **Parsing.** Malformed model output re-asks rather than escalating, invented
  JSON keys are dropped, and near-miss keys (`problem`, `location`) are mapped
  onto the schema.
- **The webhook flow.** Demo mode texts back, forward mode dials the owner,
  `/missed` only texts back when the owner didn't answer, a bad Twilio signature
  gets a 403 once `TWILIO_AUTH_TOKEN` is set, Twilio retries are deduped by
  `MessageSid`, conversations are capped at 12 customer turns, and if the agent
  throws, the caller still gets a fallback text and the owner gets paged.
- **TwiML escaping.** A model reply containing
  `</Message><Redirect>http://evil</Redirect>` parses back as exactly one
  `<Message>` and no `<Redirect>`, and `Smith & Sons` in the business name stays
  well-formed. Before this fix landed in October 2026, only `&` was escaped. A
  reply steered by a hostile SMS could inject live TwiML verbs, which made the
  old claim that a hostile text "can never cause an action" false.
- **The local-only guard** rejects requests with a foreign Host or Origin header
  (DNS rebinding, cross-site form POSTs).

`evals/` holds 12 live behavioral cases graded by deterministic checks: never
quotes a price, asks one question per text, escalates anger, refuses DIY gas
advice. They call the real API, so they're deliberately kept out of CI. Results
are gitignored, so this repo doesn't claim a pass rate.

## Known limits

These are real gaps, and they're part of why this would have needed more work
before a pilot.

- **The gas regex misses many real phrasings.** While archiving I tested it on
  18 ways people describe a gas or CO problem. It caught 8 and missed 10,
  including "gas is leaking from the stove", "rotten egg smell by the water
  heater", "it reeks of gas", "hissing sound from the gas line" and
  "carbon-monoxide alarm" (with a hyphen). A miss falls through to the model,
  which is prompted to escalate emergencies, but without the verbatim safety
  line and with no eval coverage for those phrasings. ARTICLE.md calls the gate
  100% reliable. That's only true for phrasings it matches.
- **Stalled conversations are never handed off.** The owner hears about a
  conversation only on DONE, ESCALATE, the turn cap, or an agent error. If a
  caller answers one question and goes quiet, nothing fires: no timer, no
  partial summary. What they typed sits in `conversations.jsonl` and never
  reaches `/leads`.
- **`/rollup` counts anyone who texts as a missed call.** Receipts are grouped
  by phone number, not by call. Someone who texts the number without ever
  calling still adds to `missed_calls_caught` and `textbacks_sent`, even though
  no text-back went out. A caller who replied and then stalled shows up as
  `no_reply_yet`, because CONTINUE turns don't log a receipt. And since the last
  outcome per number wins across all time, a repeat customer's second job
  overwrites their first.
- **"Estimated revenue recovered" is a guess.** It's a hardcoded table of
  ballpark job values times a 0.4 close rate. No real plumber's numbers were
  ever used to check it.
- **The price, arrival-time and DIY boundaries are enforced by the prompt and
  checked by evals, not by code.** Only the gas/CO, water and injection gates
  are deterministic.
- **State lives in memory.** A restart mid-conversation drops the working
  state; the JSONL audit trail survives.
- **Never piloted.** The live Twilio loop (real call → SMS thread → owner page)
  has no automated test, and the product never ran for a real business.

## Run it locally

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt
pytest                         # hermetic: no keys, no network, no repo writes
ruff check .
python evals/run_evals.py      # live model evals; needs ANTHROPIC_API_KEY and costs money
```

A live demo needs a Twilio number, an Anthropic key and ngrok. The steps are in
[SETUP.md](SETUP.md). The reasoning behind each cut (SMS instead of voice, no
RAG, in-memory state) is in [TRADEOFFS.md](TRADEOFFS.md).

## Repo layout

```
app/main.py      FastAPI webhooks, signature check, local-only guard, turn cap, retry dedupe, fallback
app/agent.py     deterministic gates + the single structured Haiku call + output parsing
app/state.py     conversation state (in-memory, JSONL audit trail)
app/notify.py    owner handoff: local JSONL always; SMS, email, webhook when configured
app/receipt.py   value receipts and the /rollup scoreboard
tests/           64 hermetic pytest tests
evals/           12 live behavioral cases against the production prompt
```

MIT licensed. Third-party licenses are listed in [NOTICE.md](NOTICE.md).
