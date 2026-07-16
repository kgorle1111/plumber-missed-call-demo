"""Receipt math, rollup grouping, conversation state, and the owner handoff —
the paths that decide whether the pilot scoreboard can be trusted."""
from app import notify, receipt, state


class TestEstimatedValue:
    def test_job_table_match(self):
        assert receipt.estimated_value({"issue": "Water Heater is dead"}) == 1800 * 0.4
        assert receipt.estimated_value({"issue": "need the whole house repiped, repipe quote"}) == 8000 * 0.4

    def test_unknown_issue_gets_service_call_average(self):
        assert receipt.estimated_value({"issue": "weird banging in the walls"}) == 350 * 0.4

    def test_no_issue_is_zero(self):
        assert receipt.estimated_value({}) == 0.0
        assert receipt.estimated_value(None) == 0.0


class TestRollup:
    def test_last_outcome_wins_no_double_count(self):
        receipt.log_event("+1A", "textback_sent")
        receipt.log_event("+1A", "lead_captured", captured={"issue": "water heater"})
        receipt.log_event("+1B", "textback_sent")
        roll = receipt.rollup()
        assert roll["missed_calls_caught"] == 2
        assert roll["leads_captured"] == 1
        assert roll["no_reply_yet"] == 1
        assert roll["estimated_revenue_recovered"] == 1800 * 0.4

    def test_empty_log_is_empty_dict(self):
        assert receipt.rollup() == {}


class TestState:
    def test_merge_never_overwrites_earlier_capture(self):
        state.merge_captured("+1C", {"issue": "clogged sink"})
        state.merge_captured("+1C", {"issue": "DIFFERENT", "name": "Sam"})
        c = state.get("+1C")["captured"]
        assert c["issue"] == "clogged sink" and c["name"] == "Sam"

    def test_photo_count_accumulates(self):
        state.merge_captured("+1D", {"photo_count": 1})
        state.merge_captured("+1D", {"photo_count": 2})
        assert state.get("+1D")["captured"]["photo_count"] == 3

    def test_close_drops_from_memory_keeps_audit(self, isolate_files):
        state.append("+1E", "customer", "hi")
        state.close("+1E")
        assert "+1E" not in state._CONVERSATIONS
        assert (isolate_files / "conversations.jsonl").exists()

    def test_message_sid_dedupe(self):
        assert not state.seen("SM1")
        assert state.seen("SM1")
        assert not state.seen("")  # missing sid never blocks processing


class TestHandoff:
    def test_persisted_locally_with_empty_fields_stripped(self, isolate_files):
        m = notify.handoff("+1F", "lead_captured", "done",
                           {"name": "Sam", "address": None, "photo_count": 0},
                           [("agent", "hi"), ("customer", "sink broke")])
        assert m["captured"] == {"name": "Sam"}
        assert (isolate_files / "messages.jsonl").read_text().count("\n") == 1

    def test_emergency_summary_screams(self):
        s = notify._summary({"kind": "emergency", "caller": "+1G", "captured": {},
                             "reason": "gas", "conversation": []})
        assert "EMERGENCY" in s

    def test_sms_summary_omits_transcript(self):
        msg = {"kind": "lead_captured", "caller": "+1H", "captured": {"issue": "clog"},
               "reason": "r", "conversation": ["customer: hello"]}
        assert "hello" not in notify._summary(msg, sms=True)
        assert "hello" in notify._summary(msg)
