"""Conversation state, keyed by caller phone number.

kn: in-memory dict + append-only JSONL audit trail; a restart drops mid-conversation
state (the audit line survives, the bot just re-asks). SQLite when this runs
multi-worker or a pilot shows real traffic — the interface below doesn't change.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "conversations.jsonl"

MAX_TURNS = 12  # caps token burn from spam/jailbreak loops; a real lead closes in ~5

_CONVERSATIONS: dict[str, dict] = {}
_SEEN_SIDS: set[str] = set()  # Twilio retries webhooks on timeout — dedupe by MessageSid


def seen(message_sid: str) -> bool:
    """True if this MessageSid was already processed (Twilio retry) — record it if not."""
    if not message_sid:
        return False
    if message_sid in _SEEN_SIDS:
        return True
    _SEEN_SIDS.add(message_sid)
    return False


def get(caller: str) -> dict:
    """Fetch-or-create the conversation for a caller."""
    if caller not in _CONVERSATIONS:
        _CONVERSATIONS[caller] = {
            "caller": caller,
            "started": datetime.now(timezone.utc).isoformat(),
            "call_sid": None,
            "history": [],       # [(role, text)] — role is "customer" | "agent"
            "captured": {},
            "closed": False,
        }
    return _CONVERSATIONS[caller]


def append(caller: str, role: str, text: str) -> None:
    convo = get(caller)
    convo["history"].append((role, text))
    with LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "caller": caller, "role": role, "text": text}) + "\n")


def merge_captured(caller: str, captured: dict) -> dict:
    """Fold newly captured fields in; a field captured earlier stays unless empty."""
    convo = get(caller)
    for k, v in (captured or {}).items():
        if v in (None, "", 0):
            continue
        if k == "photo_count":
            convo["captured"][k] = (convo["captured"].get(k) or 0) + v
        elif not convo["captured"].get(k):
            convo["captured"][k] = v
    return convo["captured"]


def turn_count(caller: str) -> int:
    return sum(1 for role, _ in get(caller)["history"] if role == "customer")


def close(caller: str) -> dict:
    """Mark done and drop from memory (audit trail already on disk). Returns final state."""
    convo = _CONVERSATIONS.pop(caller, None) or get(caller)
    convo["closed"] = True
    return convo


if __name__ == "__main__":
    import tempfile
    LOG = Path(tempfile.mkstemp(suffix=".jsonl")[1])  # don't pollute the repo

    append("+15550001111", "agent", "sorry we missed you")
    append("+15550001111", "customer", "sink is clogged")
    assert turn_count("+15550001111") == 1
    merge_captured("+15550001111", {"issue": "clogged sink", "name": None, "photo_count": 1})
    merge_captured("+15550001111", {"issue": "SHOULD NOT OVERWRITE", "name": "Sam", "photo_count": 2})
    c = get("+15550001111")["captured"]
    assert c["issue"] == "clogged sink" and c["name"] == "Sam" and c["photo_count"] == 3
    final = close("+15550001111")
    assert final["closed"] and "+15550001111" not in _CONVERSATIONS
    assert not seen("SM123") and seen("SM123")  # first time new, second time duplicate
    assert len(LOG.read_text().splitlines()) == 2
    print("state OK")
