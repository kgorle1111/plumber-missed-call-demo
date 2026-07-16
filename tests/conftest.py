"""Hermetic test setup — runs before any app import.

Guarantees the suite is safe and reproducible with ZERO secrets:
- neutralizes load_dotenv so the developer's real .env never leaks into tests
- strips every key / delivery target from the environment, so no test can hit the
  network (Twilio, Anthropic, email, webhooks all no-op or raise where asserted)
- redirects every file the app writes (receipts, messages, conversations) into a
  temp dir, so tests never pollute the repo
"""
import os
import pathlib
import sys

# 1) Make the repo importable and stop .env from loading.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import dotenv  # noqa: E402

dotenv.load_dotenv = lambda *a, **k: None

# 2) Scrub the environment BEFORE any app module import reads it.
for _k in ("ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
           "TWILIO_PHONE_NUMBER", "OWNER_FORWARD_NUMBER", "OWNER_NOTIFY_NUMBER",
           "OWNER_EMAIL", "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "LEAD_WEBHOOK",
           "PUBLIC_BASE_URL"):
    os.environ.pop(_k, None)
os.environ["CLOSE_RATE"] = "0.4"  # deterministic estimated_value in tests

import pytest  # noqa: E402

from app import notify, receipt, state  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_files(tmp_path, monkeypatch):
    """Every test writes its receipts/messages/conversations into its own tmp dir,
    and starts with clean in-memory conversation state."""
    monkeypatch.setattr(receipt, "LOG", tmp_path / "receipts.jsonl")
    monkeypatch.setattr(notify, "MESSAGES", tmp_path / "messages.jsonl")
    monkeypatch.setattr(state, "LOG", tmp_path / "conversations.jsonl")
    monkeypatch.setattr(state, "_CONVERSATIONS", {})
    monkeypatch.setattr(state, "_SEEN_SIDS", set())
    return tmp_path


@pytest.fixture
def decision():
    """Factory for a valid agent decision dict."""
    from app.agent import EMPTY_CAPTURED

    def _make(**over):
        d = {"decision": "CONTINUE", "intent": "new_job", "reason": "collecting",
             "captured": dict(EMPTY_CAPTURED), "reply_text": "What's your name?"}
        d["captured"].update(over.pop("captured", {}))
        d.update(over)
        return d
    return _make
