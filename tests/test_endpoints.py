"""HTTP surface: the voice→missed→textback flow, the SMS turn loop (agent mocked —
no keys, no network), signature enforcement, retries, turn cap, and the AI-down
fallback. These are the paths a live pilot exercises on day one."""
import json

import pytest
from fastapi.testclient import TestClient

from app import agent, main, receipt, state

client = TestClient(main.app)


def _sms(body, caller="+18315550100", sid=None, media=0):
    return client.post("/sms", data={"From": caller, "Body": body,
                                     "MessageSid": sid or f"SM{abs(hash(body))}",
                                     "NumMedia": str(media)})


class TestVoice:
    def test_demo_mode_says_and_texts_back(self, isolate_files):
        r = client.post("/voice", data={"From": "+18315550101", "CallSid": "CA1"})
        assert r.status_code == 200 and "<Say>" in r.text and "<Hangup/>" in r.text
        rows = (isolate_files / "receipts.jsonl").read_text().splitlines()
        assert json.loads(rows[0])["outcome"] == "textback_sent"

    def test_forward_mode_dials_owner(self, monkeypatch):
        monkeypatch.setenv("OWNER_FORWARD_NUMBER", "+18315550199")
        r = client.post("/voice", data={"From": "+18315550101", "CallSid": "CA2"})
        assert '<Dial timeout="20" action="/missed">+18315550199</Dial>' in r.text

    def test_missed_fires_textback_only_when_unanswered(self, isolate_files):
        r = client.post("/missed", data={"From": "+18315550102", "DialCallStatus": "completed"})
        assert "<Say>" not in r.text  # owner answered — no textback
        assert not (isolate_files / "receipts.jsonl").exists()
        r = client.post("/missed", data={"From": "+18315550102", "DialCallStatus": "no-answer"})
        assert "<Say>" in r.text
        assert (isolate_files / "receipts.jsonl").exists()


class TestSignature:
    def test_bad_signature_rejected_when_token_set(self, monkeypatch):
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token123")
        for path in ("/voice", "/missed", "/sms"):
            assert client.post(path, data={"From": "+1"}).status_code == 403


class TestSmsTurn:
    def test_continue_replies_and_merges_capture(self, monkeypatch, decision):
        monkeypatch.setattr(agent, "decide",
                            lambda *a, **k: decision(captured={"issue": "clogged sink"}))
        r = _sms("my sink is clogged")
        assert "<Message>What's your name?</Message>" in r.text
        assert state.get("+18315550100")["captured"]["issue"] == "clogged sink"

    def test_done_notifies_owner_logs_lead_and_closes(self, monkeypatch, decision, isolate_files):
        monkeypatch.setattr(agent, "decide", lambda *a, **k: decision(
            decision="DONE", reply_text="Dave will call you shortly.",
            captured={"issue": "water heater leaking", "name": "Sam",
                      "address": "212 Ocean St", "preferred_time": "ASAP"}))
        _sms("212 Ocean St, ASAP, I'm Sam — water heater leaking")
        row = json.loads((isolate_files / "receipts.jsonl").read_text().splitlines()[-1])
        assert row["outcome"] == "lead_captured"
        assert row["estimated_value"] == 1800 * 0.4
        msg = json.loads((isolate_files / "messages.jsonl").read_text())
        assert msg["kind"] == "lead_captured" and msg["captured"]["name"] == "Sam"
        assert "+18315550100" not in state._CONVERSATIONS  # closed

    def test_emergency_guard_end_to_end_no_key_needed(self, isolate_files):
        r = _sms("I smell gas in the house")
        assert "911" in r.text
        row = json.loads((isolate_files / "receipts.jsonl").read_text().splitlines()[-1])
        assert row["outcome"] == "emergency_escalated"
        msg = json.loads((isolate_files / "messages.jsonl").read_text())
        assert msg["kind"] == "emergency"

    def test_agent_error_falls_back_and_pages_owner(self, monkeypatch, isolate_files):
        monkeypatch.setattr(agent, "decide",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        r = _sms("sink clogged")
        assert main.FALLBACK_SMS in r.text  # caller never dead-ends
        msg = json.loads((isolate_files / "messages.jsonl").read_text())
        assert "agent error" in msg["reason"]

    def test_twilio_retry_deduped(self, monkeypatch, decision):
        calls = []
        monkeypatch.setattr(agent, "decide",
                            lambda *a, **k: calls.append(1) or decision())
        _sms("hello", sid="SM_RETRY")
        _sms("hello", sid="SM_RETRY")
        assert len(calls) == 1  # second delivery ignored

    def test_turn_cap_escalates_instead_of_burning_tokens(self, monkeypatch, decision):
        monkeypatch.setattr(agent, "decide", lambda *a, **k: decision())
        for i in range(state.MAX_TURNS):
            _sms(f"msg {i}", sid=f"SM_CAP_{i}")
        r = _sms("one too many", sid="SM_CAP_LAST")
        assert main.TURN_CAP_SMS in r.text


class TestDashboard:
    def test_leads_returns_handoffs_newest_first(self, isolate_files):
        from app import notify
        notify.handoff("+1X", "lead_captured", "r", {"issue": "clog"}, [])
        notify.handoff("+1Y", "emergency", "gas", {}, [])
        rows = client.get("/leads").json()
        assert [r["caller"] for r in rows] == ["+1Y", "+1X"]

    def test_leads_empty_when_no_file(self):
        assert client.get("/leads").json() == []

    def test_dashboard_serves_html(self):
        r = client.get("/dashboard")
        assert r.status_code == 200 and "scoreboard" in r.text

    def test_token_gates_pii_endpoints_but_not_rollup(self, monkeypatch):
        monkeypatch.setenv("DASH_TOKEN", "s3cret")
        assert client.get("/leads").status_code == 403
        assert client.get("/dashboard").status_code == 403
        assert client.get("/leads?key=s3cret").status_code == 200
        assert client.get("/dashboard?key=s3cret").status_code == 200
        assert client.get("/rollup").status_code == 200  # aggregate only, stays open


class TestOps:
    def test_health(self):
        assert client.get("/health").json()["ok"] is True

    def test_rollup_endpoint_matches_receipts(self, monkeypatch, decision):
        client.post("/voice", data={"From": "+18315550107", "CallSid": "CA9"})
        assert client.get("/rollup").json() == receipt.rollup()
        assert client.get("/rollup").json()["missed_calls_caught"] >= 1


@pytest.fixture(autouse=True)
def _no_forward(monkeypatch):
    """Default to pure demo mode unless a test opts in."""
    monkeypatch.delenv("OWNER_FORWARD_NUMBER", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
