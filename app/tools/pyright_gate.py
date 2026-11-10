"""Pyright's errors as a per-file ledger that may only go down. Run from the repo root,
in CI and locally.

tools/held/pyright.json holds `{file: {rule: count}}`. A file and rule over their
held count, or new, fails naming both. Under it fails too, saying to lower it, so the
ledger stays what the code is and a fix in one file cannot pay for a new error in
another. Paths listed under "strict" in pyrightconfig.json must have no errors,
whatever is held. `--write` rewrites the ledger from today's errors (seed once; never
to let an error through). `--report` prints the count and the top rules and never
fails.

Template from the agentic-engineering skill. Needs `pyright` on PATH (pip install
pyright) and a pyrightconfig.json naming the source packages under "include"."""

import collections
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from held_ledger import Ledger, dump, load, problems, tally, total

HELD = ROOT / "tools" / "held" / "pyright.json"
Diagnostic = dict[str, Any]


def run() -> list[Diagnostic]:
    proc = subprocess.run(
        ["pyright", "--outputjson"], cwd=ROOT, capture_output=True, text=True
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(
            f"pyright produced no JSON (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}"
        )
    if data.get("summary", {}).get("filesAnalyzed", 0) == 0:
        sys.exit(
            "pyright analysed no files: check pyrightconfig.json 'include'; "
            "a gate that sees nothing passes on nothing"
        )
    return [d for d in data["generalDiagnostics"] if d["severity"] == "error"]


def rel(file: str) -> str:
    """A diagnostic's file as the ledger keys it: relative to `app/`, or to the repo for the bridge beside it."""
    path = Path(file).resolve()
    return path.relative_to(ROOT if ROOT in path.parents else ROOT.parent).as_posix()


def ledger_of(errors: list[Diagnostic]) -> Ledger:
    return tally(
        [
            (rel(e["file"]), e.get("rule", "?"))
            for e in errors
        ]
    )


def main(argv: list[str]) -> int:
    errors = run()
    found = ledger_of(errors)
    if "--write" in argv:
        HELD.parent.mkdir(parents=True, exist_ok=True)
        HELD.write_text(dump(found))
        print(
            f"wrote {HELD.relative_to(ROOT)}: "
            f"{total(found)} errors in {len(found)} files"
        )
        return 0
    held = load(HELD)
    cfg = ROOT / "pyrightconfig.json"
    strict = (
        [p.rstrip("/").removeprefix("../") for p in json.loads(cfg.read_text()).get("strict", [])]
        if cfg.exists()
        else []
    )
    bad = [
        e
        for e in errors
        if any(
            rel(e["file"]).startswith(p)
            for p in strict
        )
    ]
    print(f"pyright errors {len(errors)}, held {total(held)}")
    for rule, c in collections.Counter(e.get("rule", "?") for e in errors).most_common(
        8
    ):
        print(f"  {c:5d} {rule}")
    if "--report" in argv:
        return 0
    for e in bad:
        print(
            f"STRICT {e['file']}:{e['range']['start']['line'] + 1}: "
            f"{e['message'].splitlines()[0]}"
        )
    wrong = problems(
        found,
        held,
        "fix them (`pyright` shows where)",
        "python tools/pyright_gate.py --write",
    )
    for line in wrong:
        print("PYRIGHT: " + line)
    return 1 if bad or wrong else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
