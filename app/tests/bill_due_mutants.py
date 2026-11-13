"""Plants each wrong implementation of `bill_due_MUTANTS.txt` in turn and runs `tests/test_bill_due.py`; a mutant is
caught when that run fails. Run from `app/` with the test services' environment: `python tests/bill_due_mutants.py`."""

import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
SENSES, TOOLS = "ashley/senses/", "ashley/tools/"
MUTANTS: list[tuple[str, str, str, str]] = [
    ("D1", SENSES + "bill_due.py", "not 0 <= (due - today).days <= a.rule.due_days", "not (due - today).days <= a.rule.due_days"),
    ("D2", SENSES + "bill_due.py", "<= a.rule.due_days", "< a.rule.due_days"),
    ("D3", SENSES + "bill_due.py", "r.account_id != a.rule.account_id \\", "False \\"),
    ("D4", SENSES + "bill_due.py", "if r.ended or r.kind", "if r.kind"),
    ("D5", SENSES + "bill_due.py", 'r.kind != "expense" or ', ""),
    ("D6", SENSES + "bill_due.py", "or not names_match(a.rule, tuple(n for n in (r.merchant, r.name) if n)):", ":"),
    ("D7", SENSES + "postgres_deposits.py", "|| %s || ':' || %s, 'reminder'", "|| %s || '' || '', 'reminder'"),
    ("D8", SENSES + "postgres_deposits.py", "'bill:' || id || ':' || %s || ':' || %s", "'bill:' || id || ':' || %s || ':' || %s || now()"),
    ("D9", SENSES + "postgres_deposits.py", "FROM wakes WHERE id = %s AND trigger = 'event' AND settled_at IS NULL \"\n            \"ON CONFLICT (household_id, event_id) DO NOTHING RETURNING id\",\n            (recurring_id", "FROM wakes WHERE id = %s \"\n            \"ON CONFLICT (household_id, event_id) DO NOTHING RETURNING id\",\n            (recurring_id"),
    ("D10", SENSES + "deposit_sense.py", "if bills else []", "if True else []"),
    ("D11", SENSES + "deposit_rule.py", "rule.below_cents is not None or rule.due_days is not None or not", "rule.below_cents is not None or not"),
    ("D12", TOOLS + "../channels/wake/reminder_turn.py", "{', and it pays itself' if landed.autopay else ''}", ""),
    ("D13", TOOLS + "money_rule_args.py", "not 0 <= raw <= CONFIG.max_due_days", "not 0 <= raw"),
    ("D14", TOOLS + "money_rule_args.py", "!= 1:", "< 1:"),
    ("D15", SENSES + "deposit_sense.py", "a.rule.below_cents is None and a.rule.due_days is None]", "a.rule.below_cents is None]"),
]


def main() -> int:
    survived = 0
    for name, rel, old, new in MUTANTS:
        path = APP / rel
        original = path.read_text()
        assert original.count(old) == 1, f"{name}: anchor not unique in {rel}"
        path.write_text(original.replace(old, new, 1))
        try:
            ran = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-n", "2", "tests/test_bill_due.py"],
                                 cwd=APP, capture_output=True, text=True, timeout=300)
        finally:
            path.write_text(original)
        caught = ran.returncode != 0
        survived += not caught
        print(name, "caught" if caught else "SURVIVED", flush=True)
    return survived


if __name__ == "__main__":
    sys.exit(main())
