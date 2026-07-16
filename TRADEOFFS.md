# TRADEOFFS — what I cut and what it costs

I set the bar for this build differently from the voice agent I'd built before:
no latency budget (SMS is async — 3 seconds is instant), but a **hand-off
budget** instead. I walk away after setup, so I made every component survive
with nobody watching. Anything that would need me babysitting it, I didn't ship.

## SMS instead of voice — the medium IS the trade

My earlier build (a real-time voice agent for an auto detailing studio) answers
the phone live. Here I deliberately let the call ring out and moved the
conversation to SMS. Three reasons I made that call:

- **Cost**: a voice minute runs ~$0.25 all-in (STT+LLM+TTS+telephony); a whole
  SMS conversation is ~$0.07. At plumber volumes the voice bill would need a
  monthly retainer to justify — SMS runs on pocket change, which is the only
  thing that makes a one-time-fee hand-off viable.
- **Risk**: a voice agent that mishears an address books a wrong-house visit. I
  wanted the thread written down so the plumber reads exactly what the customer
  typed.
- **Fit**: callers already expect "on a job, text me" from a tradesman. Nobody
  expects a solo plumber to have a receptionist — a text back reads as *him*.

What I gave up: the caller who won't text (older customers especially — a real
segment for plumbing). They still reach voicemail like they do today; I let the
pilot's rollup measure the reply rate, and if it's low the voice build is the
upgrade path — I've already built it.

## No RAG — deliberately

The detailing agent needed a KB (packages, prices, policies). This agent's job
is *capture*, not *answer*: issue, address, name, time. I left retrieval out
because there are no approved facts to ground — the one thing customers ask
(price) is the one thing it must never answer, so RAG here would be machinery in
service of a failure mode. If a pilot plumber wants FAQ answering ("do you do
tankless?"), I'll add a KB + retrieval layer then — scoped and priced as an
upgrade, not smuggled into the demo.

## In-memory conversation state — with a JSONL audit trail

I keyed state to a dict on the phone number, capped it at `MAX_TURNS=12`, and
appended every turn to `conversations.jsonl`. A server restart mid-conversation
loses the working state; the bot re-asks one question and the audit line
survives. For a demo and a single-worker pilot I judged this the right rung —
SQLite would add a schema, migrations, and a file to manage, all to cover a
failure mode (a restart during an active 5-minute SMS exchange) that's rare and
self-healing. I kept the state module's interface stable so it graduates without
a rewrite.
`kn: in-memory + jsonl; sqlite when multi-worker or a pilot shows real traffic.`

## Deterministic guard before the LLM — the one thing I refused to compromise

Gas leak / CO texts get a verbatim safety line ("leave now, 911 / PG&E") in 0 ms
with 100% reliability. I would not let a life-safety reply depend on a model
behaving, parsing, or even being up. I did the same for injection: regex first,
and I gave the agent no tools, so even a successful jailbreak can only produce a
strange text.

The asymmetric cost profile is why I built it this way: a false-positive gate
(customer says "gas water heater" meaning an appliance job) costs one
over-cautious reply; a false negative on a real leak is unbounded. I tuned the
regex to fire on leak/smell phrasing and stay silent on appliance phrasing, and
pinned that line with both the eval suite and unit tests.

## One LLM call per turn, JSON contract, parse-failure = re-ask

Same reasoning as my voice build, but I weighed a harsher penalty here: a parse
failure that silently ESCALATEd would SMS the *owner's personal phone* about
nothing — do that twice and he turns the product off. So I made malformed
replies re-ask the customer; real escalations fire only from the model's
explicit decision or the deterministic guard.

## Twilio retry dedupe + turn cap — cheap, load-bearing

Twilio re-POSTs webhooks on timeout, so without `MessageSid` dedupe a slow LLM
call double-replies and double-pages — I added the dedupe to kill that. The
12-turn cap I put in bounds token burn from spam or a chatty jailbreak attempt
at ~$0.04 per number, without standing up any rate-limit infrastructure.

## What I skipped, and the trigger I set for each

- **Docker / deploy config** — the demo runs on a laptop + ngrok. I'll add it
  when the first pilot converts and it moves to Fly/Render (the voice build's
  Dockerfile drops in).
- **Scheduling / calendar writes** — I kept this capture-only, like the voice
  build. The agent never books; the owner calls back. I'll add it only if a
  pilot owner asks, and only as a human-gated action.
- **Observability (Langfuse)** — receipts + conversations.jsonl are enough eyes
  for one pilot. I'll add it at 3+ concurrent clients.
- **Landline detection** — a text-back to a landline vanishes silently. Twilio
  Lookup ($0.008/query) can flag it; I'll add it if the pilot rollup shows a
  suspicious no-reply rate.
- **Owner quote-from-photo, review-request flow** — I scoped these as sellable
  add-ons, not demo scope. They live in the pitch deck, not the codebase yet.
