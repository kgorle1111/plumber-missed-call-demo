# SETUP — from zero to a live demo number

> Kept for completeness — this is how I'd have deployed it to a pilot. The
> go-to-market is shelved (see [ARTICLE.md](ARTICLE.md)); the steps below still
> stand up the demo end to end.

## 1. Local

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt
python -m app.agent && python -m app.state && python -m app.notify && python -m app.receipt
pytest        # all green, no keys needed
```

## 2. Keys

| Key | Where |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | console.twilio.com dashboard |
| `TWILIO_PHONE_NUMBER` | Console → Phone Numbers → Buy a number (~$1.15/mo). Pick a local 831 number — a Santa Cruz caller texting with an 831 number reads as local. Needs **Voice + SMS + MMS** capabilities. |

`cp .env.example .env` and fill those four. Leave `OWNER_FORWARD_NUMBER` empty
for the pitch demo (every call is "missed" by design); set it to the plumber's
cell for a real pilot.

## 3. Wire the webhooks

```bash
uvicorn app.main:app --port 5060
ngrok http 5060
```

In the Twilio Console → your number → Configure:
- **Voice → A call comes in** → Webhook → `https://<ngrok>.ngrok.app/voice` (POST)
- **Messaging → A message comes in** → Webhook → `https://<ngrok>.ngrok.app/sms` (POST)

Set `PUBLIC_BASE_URL=https://<ngrok>.ngrok.app` in `.env` so signature
validation matches the URL Twilio actually signed. Restart uvicorn after
editing `.env`.

## 4. Test the loop

1. Call the Twilio number from your cell → hear the "on a job" message → hang up.
2. Within seconds: the text-back arrives.
3. Reply "water heater is leaking" → agent asks for the address, one field per text.
4. Finish the flow → check `messages.jsonl` for the owner handoff and
   `curl localhost:5060/rollup` for the scoreboard.
5. Text "I smell gas" from a second conversation → verbatim 911/PG&E line,
   instant escalation. This is the safety demo — show it in every pitch.

## 5. A2P 10DLC (before a real pilot — not needed for self-demo)

US carriers require business SMS registration. In Twilio: **Messaging →
Regulatory Compliance → A2P 10DLC** → register the *plumber's* business (their
EIN, ~30 min form, one-time ~$4 + $2/mo campaign fee, sole-prop path exists for
no-EIN owners). Do this WITH the owner at setup — it's their brand and their
number. Unregistered traffic gets filtered; don't run a pilot without it.

## 6. Per-client hand-off checklist

- [ ] Their Twilio account, their Anthropic key, their card on both — you hold nothing
- [ ] `BUSINESS_NAME` / `OWNER_NAME` / `OWNER_FORWARD_NUMBER` / `OWNER_NOTIFY_NUMBER` set
- [ ] A2P registration submitted
- [ ] `CLOSE_RATE` + `JOB_VALUE` table sanity-checked against their real numbers
- [ ] One-page runbook delivered: what it does, where the accounts live, who to
      call when Twilio breaks (Twilio, not you)
