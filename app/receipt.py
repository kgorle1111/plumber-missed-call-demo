"""Value receipt: append-only event log, one line per conversation milestone, so a
business rollup exists with zero infra. A win the owner can't see gets cancelled.

Events are grouped by call/caller and the LAST outcome wins — so a missed call that
starts as "textback_sent" and later becomes "lead_captured" counts once, as a lead.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "receipts.jsonl"

# Owner-approved average job values by issue keyword, and the callback close rate.
# kn: ballpark Santa Cruz numbers for the demo — replace with the pilot plumber's
# real averages in week one; the rollup math doesn't change.
JOB_VALUE = {
    "repipe": 8000, "sewer": 3500, "water heater": 1800, "gas": 800,
    "leak": 450, "toilet": 350, "drain": 300, "clog": 300,
    "faucet": 250, "sink": 250, "disposal": 250,
}
DEFAULT_JOB_VALUE = 350  # average service call when the issue matches nothing above
CLOSE_RATE = float(os.getenv("CLOSE_RATE", "0.4"))


def estimated_value(captured):
    """Estimated recovered revenue = matched job value x owner-approved close rate."""
    issue = ((captured or {}).get("issue") or "").lower()
    for key, val in JOB_VALUE.items():
        if key in issue:
            return round(val * CLOSE_RATE, 2)
    return round(DEFAULT_JOB_VALUE * CLOSE_RATE, 2) if issue else 0.0


def log_event(caller, outcome, intent=None, reason=None, captured=None):
    """Append one receipt event. outcome: textback_sent | lead_captured | emergency_escalated
    | escalated | turn_capped."""
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "caller": caller,
        "outcome": outcome,
        "intent": intent,
        "reason": reason,
        "estimated_value": estimated_value(captured) if outcome == "lead_captured" else 0.0,
    }
    with LOG.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def rollup(path=None):
    """Business-terms rollup: group events by caller, last outcome wins.
    LOG is resolved at call time (not as a default arg) so tests/tools that
    repoint receipt.LOG see the right file."""
    path = Path(path or LOG)
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    final: dict[str, dict] = {}
    for r in rows:
        final[r["caller"]] = r  # chronological file order — later events overwrite
    outcomes = [r["outcome"] for r in final.values()]
    recovered = round(sum(r["estimated_value"] for r in final.values()), 2)
    leads = outcomes.count("lead_captured")
    return {
        "missed_calls_caught": len(final),
        "textbacks_sent": len(final),  # every conversation starts with one
        "leads_captured": leads,
        "emergencies_escalated": outcomes.count("emergency_escalated"),
        "escalated_to_owner": outcomes.count("escalated"),
        "no_reply_yet": outcomes.count("textback_sent"),
        "estimated_revenue_recovered": recovered,
        "avg_value_per_lead": round(recovered / leads, 2) if leads else 0.0,
    }


if __name__ == "__main__":
    import tempfile
    LOG = Path(tempfile.mkstemp(suffix=".jsonl")[1])

    assert estimated_value({"issue": "water heater is dead"}) == round(1800 * CLOSE_RATE, 2)
    assert estimated_value({"issue": "kitchen DRAIN totally clogged"}) == round(300 * CLOSE_RATE, 2)
    assert estimated_value({"issue": "weird noise in the walls"}) == round(350 * CLOSE_RATE, 2)
    assert estimated_value({}) == 0.0
    print("value table OK")

    log_event("+1555A", "textback_sent")
    log_event("+1555A", "lead_captured", intent="new_job", captured={"issue": "water heater leaking"})
    log_event("+1555B", "textback_sent")
    log_event("+1555C", "textback_sent")
    log_event("+1555C", "emergency_escalated", intent="emergency")
    roll = rollup(LOG)
    assert roll["missed_calls_caught"] == 3
    assert roll["leads_captured"] == 1 and roll["no_reply_yet"] == 1
    assert roll["emergencies_escalated"] == 1
    assert roll["estimated_revenue_recovered"] == round(1800 * CLOSE_RATE, 2)
    print("rollup OK", roll["estimated_revenue_recovered"])
