"""Missed-call → SMS text-back webhooks.

Call flow
    caller dials the Twilio number → POST /voice
      OWNER_FORWARD_NUMBER set   → <Dial> the owner's real cell (20 s), action=/missed
      unset (pure demo mode)     → every call is "missed": short message + text-back
    POST /missed  → owner didn't pick up → same message + text-back
    POST /sms     → the SMS conversation: guard → one Haiku call → reply TwiML
                    DONE/ESCALATE → owner handoff (notify.py) + value receipt

Security
    - X-Twilio-Signature validated on every webhook once TWILIO_AUTH_TOKEN is set
      (unset = local dev / tests only).
    - Inbound SMS is untrusted data — guards + prompt handle injection; the agent
      has no tools, so the blast radius of a hostile text is a weird reply, never
      an action.
    - If the agent path throws, the caller still gets a fallback SMS pointing at
      the owner's line. A missed call never dead-ends.
"""
import json
import os
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse

from app import agent, notify, receipt, state

load_dotenv()

app = FastAPI(title="plumber-missed-call-demo")

# --- localhost guard -------------------------------------------------------
# Rejects requests whose Host or Origin isn't local. The Host check stops DNS
# rebinding (evil.com resolving to 127.0.0.1 arrives with Host: evil.com); the
# Origin check stops cross-origin browser POSTs — multipart/form bodies skip
# CORS preflight, so without it any webpage the operator visits could fire
# uploads that spend real API money. curl/httpx send no Origin and pass.
# "testserver" is starlette's TestClient default host.
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def _guard_hostname(value: str) -> str:
    if "//" not in value:
        value = "//" + value
    return urlsplit(value).hostname or ""


def _allowed_hosts() -> set[str]:
    """PUBLIC_BASE_URL (the ngrok tunnel Twilio posts through) is read per
    request — it changes every ngrok restart and .env reloads on relaunch."""
    hosts = set(_LOCAL_HOSTS)
    base = os.getenv("PUBLIC_BASE_URL")
    if base:
        hosts.add(_guard_hostname(base))
    return hosts


@app.middleware("http")
async def localhost_guard(request: Request, call_next):
    if _guard_hostname(request.headers.get("host", "")) not in _allowed_hosts():
        return JSONResponse(
            {"detail": "unrecognized Host header — this server only answers as localhost"}, status_code=403
        )
    origin = request.headers.get("origin")
    if origin and _guard_hostname(origin) not in _allowed_hosts():
        return JSONResponse({"detail": "cross-origin requests are not accepted"}, status_code=403)
    return await call_next(request)


BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Harbor Plumbing (demo)")
OWNER_NAME = os.getenv("OWNER_NAME", "Dave")

TEXTBACK = (f"Hey, this is {BUSINESS_NAME} — sorry we missed your call, we're on a job. "
            f"What's going on with your plumbing? Reply here with the issue and your address "
            f"and {OWNER_NAME} will get right back to you. Photos help too.")
FALLBACK_SMS = (f"Sorry — something glitched on our end. {OWNER_NAME} sees your messages "
                "and will call you back shortly.")
TURN_CAP_SMS = (f"Thanks — I've passed everything to {OWNER_NAME} and he'll call you to sort "
                "out the rest.")
MISSED_SAY = (f"Thanks for calling {BUSINESS_NAME}. We're on a job right now — "
              "you'll get a text from us in a few seconds.")


def _twiml(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


def _say_and_hangup() -> Response:
    return _twiml(f"<Response><Say>{MISSED_SAY}</Say><Hangup/></Response>")


def _reply_sms(text: str) -> Response:
    # &-escape is enough here: reply_text never legitimately contains < or >.
    return _twiml(f"<Response><Message>{text.replace('&', '&amp;')}</Message></Response>")


async def _form(request: Request) -> dict:
    return {k: v for k, v in (await request.form()).items()}


def _signature_ok(request: Request, form: dict) -> bool:
    """Validate X-Twilio-Signature. No auth token set = dev mode, skip (never in prod)."""
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if not token:
        return True
    from twilio.request_validator import RequestValidator
    # Behind ngrok/a proxy the request URL is the private one; Twilio signed the public one.
    base = os.getenv("PUBLIC_BASE_URL")
    url = f"{base.rstrip('/')}{request.url.path}" if base else str(request.url)
    return RequestValidator(token).validate(url, form, request.headers.get("X-Twilio-Signature", ""))


def _send_sms(to: str, body: str) -> bool:  # pragma: no cover — network
    """Outbound SMS via Twilio REST (the text-back; conversation replies use TwiML).
    Without creds (local dev) it just logs, so the flow is still exercisable."""
    sid, token, from_ = (os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"),
                         os.getenv("TWILIO_PHONE_NUMBER"))
    if not (sid and token and from_):
        print(f"[dev] would SMS {to}: {body}")
        return False
    from twilio.rest import Client
    Client(sid, token).messages.create(to=to, from_=from_, body=body)
    return True


def _fire_textback(caller: str) -> None:
    if not caller:
        return
    _send_sms(caller, TEXTBACK)
    state.append(caller, "agent", TEXTBACK)
    receipt.log_event(caller, "textback_sent")


@app.get("/health")
def health():
    return {"ok": True, "business": BUSINESS_NAME}


@app.get("/rollup")
def rollup():
    """Aggregate scoreboard — no PII, safe to leave open."""
    return receipt.rollup()


def _dash_ok(request: Request) -> bool:
    """Leads + dashboard show names/addresses/phones. If DASH_TOKEN is set, require
    ?key=<token>. Unset = local dev only — never run a pilot on ngrok without it."""
    token = os.getenv("DASH_TOKEN")
    return not token or request.query_params.get("key") == token


@app.get("/leads")
def leads(request: Request):
    """Recent owner handoffs (captured leads + escalations), newest first."""
    if not _dash_ok(request):
        return Response(status_code=403)
    if not notify.MESSAGES.exists():
        return []
    rows = [json.loads(line) for line in notify.MESSAGES.read_text().splitlines()[-50:]]
    return list(reversed(rows))


@app.get("/dashboard")
def dashboard(request: Request):
    if not _dash_ok(request):
        return Response(status_code=403)
    return HTMLResponse(DASHBOARD_HTML.replace("__BUSINESS__", BUSINESS_NAME))


# kn: one self-contained page, no build step, no framework — it renders two
# GETs. A real multi-client dashboard is a separate product decision.
DASHBOARD_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__BUSINESS__ — missed-call scoreboard</title>
<style>
  body{font-family:-apple-system,system-ui,sans-serif;margin:2rem auto;max-width:720px;padding:0 1rem;color:#1a202c}
  h1{font-size:1.3rem} .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem}
  .tile{border:1px solid #e2e8f0;border-radius:10px;padding:.9rem}
  .tile b{display:block;font-size:1.7rem} .tile span{font-size:.8rem;color:#64748b}
  .money b{color:#166534}
  table{width:100%;border-collapse:collapse;margin-top:1.5rem;font-size:.9rem}
  td,th{text-align:left;padding:.45rem .5rem;border-bottom:1px solid #e2e8f0;vertical-align:top}
  .EMERGENCY{color:#b91c1c;font-weight:600}
  @media(prefers-color-scheme:dark){body{background:#0f172a;color:#e2e8f0}
    .tile{border-color:#334155}.tile span{color:#94a3b8}td,th{border-color:#334155}.money b{color:#4ade80}}
</style></head><body>
<h1>__BUSINESS__ — missed-call scoreboard</h1>
<div class="tiles" id="tiles">loading…</div>
<table><thead><tr><th>when</th><th>type</th><th>details</th></tr></thead><tbody id="rows"></tbody></table>
<script>
const key = new URLSearchParams(location.search).get('key');
const q = key ? `?key=${encodeURIComponent(key)}` : '';
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
fetch('/rollup').then(r => r.json()).then(r => {
  const t = (label, val, cls='') =>
    `<div class="tile ${cls}"><b>${esc(val)}</b><span>${label}</span></div>`;
  document.getElementById('tiles').innerHTML =
    t('missed calls caught', r.missed_calls_caught ?? 0) +
    t('leads captured', r.leads_captured ?? 0) +
    t('emergencies escalated', r.emergencies_escalated ?? 0) +
    t('est. revenue recovered', '$' + (r.estimated_revenue_recovered ?? 0).toLocaleString(), 'money');
});
fetch('/leads' + q).then(r => r.ok ? r.json() : []).then(rows => {
  document.getElementById('rows').innerHTML = rows.map(m => {
    const d = Object.entries(m.captured || {}).map(([k,v]) => `${esc(k)}: ${esc(v)}`).join(' · ');
    return `<tr><td>${esc((m.timestamp||'').slice(0,16).replace('T',' '))}</td>` +
           `<td class="${m.kind==='emergency'?'EMERGENCY':''}">${esc(m.kind)}</td>` +
           `<td>${esc(m.caller)}${d ? ' — ' + d : ''}</td></tr>`;
  }).join('') || '<tr><td colspan="3">no leads yet — go miss a call</td></tr>';
});
</script></body></html>"""


@app.post("/voice")
async def voice(request: Request):
    form = await _form(request)
    if not _signature_ok(request, form):
        return Response(status_code=403)
    forward = os.getenv("OWNER_FORWARD_NUMBER")
    if forward:
        return _twiml(f'<Response><Dial timeout="20" action="/missed">{forward}</Dial></Response>')
    _fire_textback(form.get("From", ""))
    return _say_and_hangup()


@app.post("/missed")
async def missed(request: Request):
    form = await _form(request)
    if not _signature_ok(request, form):
        return Response(status_code=403)
    if form.get("DialCallStatus") == "completed":  # owner picked up — nothing to do
        return _twiml("<Response><Hangup/></Response>")
    _fire_textback(form.get("From", ""))
    return _say_and_hangup()


@app.post("/sms")
async def sms(request: Request):
    form = await _form(request)
    if not _signature_ok(request, form):
        return Response(status_code=403)
    caller, body = form.get("From", ""), form.get("Body", "")
    photo_count = int(form.get("NumMedia", "0") or 0)

    if state.seen(form.get("MessageSid", "")):  # Twilio timeout retry — don't double-process
        return _twiml("<Response></Response>")

    convo = state.get(caller)
    state.append(caller, "customer", body or f"[{photo_count} photo(s)]")

    if state.turn_count(caller) > state.MAX_TURNS:
        notify.handoff(caller, "escalated", "turn cap reached", convo["captured"], convo["history"])
        receipt.log_event(caller, "turn_capped")
        state.close(caller)
        return _reply_sms(TURN_CAP_SMS)

    try:
        decision = agent.decide(body, convo["history"][:-1], photo_count)
    except Exception:
        # AI path down ≠ lost lead: owner gets the raw text, caller gets a human answer.
        notify.handoff(caller, "escalated", "agent error — raw message attached",
                       convo["captured"], convo["history"])
        receipt.log_event(caller, "escalated", reason="agent_error")
        return _reply_sms(FALLBACK_SMS)

    captured = state.merge_captured(caller, decision["captured"])
    state.append(caller, "agent", decision["reply_text"])

    if decision["decision"] == "ESCALATE":
        kind = "emergency" if decision["intent"] == "emergency" else "escalated"
        notify.handoff(caller, kind, decision["reason"], captured, state.get(caller)["history"])
        receipt.log_event(caller, f"{'emergency_' if kind == 'emergency' else ''}escalated",
                          intent=decision["intent"], reason=decision["reason"], captured=captured)
        state.close(caller)
    elif decision["decision"] == "DONE":
        notify.handoff(caller, "lead_captured", decision["reason"], captured,
                       state.get(caller)["history"])
        receipt.log_event(caller, "lead_captured", intent=decision["intent"],
                          reason=decision["reason"], captured=captured)
        state.close(caller)

    return _reply_sms(decision["reply_text"])
