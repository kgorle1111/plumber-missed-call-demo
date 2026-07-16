"""Behavioral evals for the SMS agent — grades the LIVE model against the exact
production prompt, distinct from pytest (deterministic code, free, offline).

Graders are deterministic invariants: decision bucket, forbidden phrases (prices,
DIY gas advice, re-asking answered fields), required phrases, question-mark and
length discipline. No LLM-as-judge — nothing here needs one.

    python evals/run_evals.py              # ~$0.02/run (12 cases, Haiku)
    python evals/run_evals.py --trials 3   # stability read (output is nondeterministic)

Needs ANTHROPIC_API_KEY. Costs real money, deliberately not in CI.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import agent  # noqa: E402

CASES = json.loads((Path(__file__).parent / "cases.json").read_text())
RESULTS = Path(__file__).parent / "results"


def grade(case, decision):
    """Return a list of failure strings (empty = pass)."""
    fails = []
    reply = decision["reply_text"]
    if decision["decision"] not in case["expect_decision"]:
        fails.append(f"decision={decision['decision']} not in {case['expect_decision']}")
    if case.get("forbid_regex") and re.search(case["forbid_regex"], reply, re.IGNORECASE):
        fails.append(f"forbidden content in reply: {reply!r}")
    if case.get("expect_regex") and not re.search(case["expect_regex"], reply, re.IGNORECASE):
        fails.append(f"missing expected content ({case['expect_regex']}): {reply!r}")
    if reply.count("?") > case.get("max_question_marks", 2):
        fails.append(f"{reply.count('?')} questions in one text: {reply!r}")
    if len(reply) > case.get("max_reply_chars", 500):
        fails.append(f"reply too long ({len(reply)} chars)")
    for field in case.get("expect_captured_nonnull", []):
        if not decision["captured"].get(field):
            fails.append(f"captured.{field} is empty")
    return fails


def run(trials):
    rows, passed = [], 0
    for case in CASES:
        for t in range(trials):
            history = [tuple(h) for h in case.get("history", [])]
            decision = agent.decide(case["body"], history, case.get("photo_count", 0))
            fails = grade(case, decision)
            ok = not fails
            passed += ok
            rows.append({"case": case["name"], "trial": t, "pass": ok,
                         "fails": fails, "decision": decision})
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {case['name']}" + (f" — {'; '.join(fails)}" if fails else ""))
    total = len(CASES) * trials
    print(f"\n{passed}/{total} passed")
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps({"passed": passed, "total": total, "rows": rows}, indent=2))
    print(f"results -> {out}")
    return passed == total


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--trials", type=int, default=1)
    sys.exit(0 if run(p.parse_args().trials) else 1)
