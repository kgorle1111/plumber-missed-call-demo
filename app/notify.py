"""Owner handoff: the plumber gets the full picture — captured job details, the
conversation, and why it's in front of them — never a cold "someone texted."

Delivery = owner SMS (if OWNER_NOTIFY_NUMBER + Twilio creds) + email (if SMTP
configured) + generic webhook (if configured). All best-effort; the message is
always persisted locally first so nothing is lost.
"""
import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib import request

MESSAGES = Path(__file__).resolve().parent.parent / "messages.jsonl"


def handoff(caller, kind, reason, captured, history):
    """Build + deliver the owner notification. Returns the message dict."""
    msg = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "caller": caller,
        "kind": kind,  # "lead_captured" | "emergency" | "escalated"
        "reason": reason,
        "captured": {k: v for k, v in (captured or {}).items() if v not in (None, "", 0)},
        "conversation": [f"{r}: {t}" for r, t in (history or [])],
    }
    with MESSAGES.open("a") as f:
        f.write(json.dumps(msg) + "\n")
    _sms(msg)
    _email(msg)
    _webhook(msg)
    return msg


def _summary(msg, sms=False):
    head = {"lead_captured": "New job captured", "emergency": "EMERGENCY — call now",
            "escalated": "Needs your call"}.get(msg["kind"], msg["kind"])
    lines = [f"{head} ({msg['caller']})"]
    lines += [f"{k}: {v}" for k, v in msg["captured"].items()]
    if not sms:
        lines += ["", f"Why: {msg['reason']}", "", "Conversation:"] + msg["conversation"]
    return "\n".join(lines)


def _sms(msg):  # pragma: no cover
    sid, token = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    to, from_ = os.getenv("OWNER_NOTIFY_NUMBER"), os.getenv("TWILIO_PHONE_NUMBER")
    if not (sid and token and to and from_):
        return
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(to=to, from_=from_, body=_summary(msg, sms=True))
    except Exception:
        pass  # local copy already saved


def _email(msg):  # pragma: no cover
    host, user, pw, to = (os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"),
                          os.getenv("SMTP_PASS"), os.getenv("OWNER_EMAIL"))
    if not (host and to):
        return
    try:
        m = EmailMessage()
        m["Subject"] = f"[missed-call bot] {msg['kind']} — {msg['caller']}"
        m["From"] = user or to
        m["To"] = to
        m.set_content(_summary(msg))
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
            s.starttls()
            if user:
                s.login(user, pw)
            s.send_message(m)
    except Exception:
        pass


def _webhook(msg):  # pragma: no cover
    url = os.getenv("LEAD_WEBHOOK")
    if not url:
        return
    try:
        req = request.Request(url, data=json.dumps(msg).encode(),
                              headers={"Content-Type": "application/json"})
        request.urlopen(req, timeout=3)
    except Exception:
        pass


if __name__ == "__main__":
    import tempfile
    MESSAGES = Path(tempfile.mkstemp(suffix=".jsonl")[1])
    m = handoff("+15550001111", "lead_captured", "all fields captured",
                {"name": "Sam", "issue": "clogged kitchen sink", "address": None, "photo_count": 0},
                [("agent", "sorry we missed you"), ("customer", "sink clogged")])
    assert m["captured"] == {"name": "Sam", "issue": "clogged kitchen sink"}
    assert "New job captured" in _summary(m)
    assert "Conversation:" not in _summary(m, sms=True)  # SMS stays short
    assert "EMERGENCY" in _summary({"kind": "emergency", "caller": "x", "captured": {},
                                    "reason": "", "conversation": []})
    print("notify OK")
