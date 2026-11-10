"""The house eval's table and JSON: per case and in total, so two runs can be diffed."""

import json
import statistics
from dataclasses import asdict
from typing import Any

from .house import RunResult, load


def _median(values: list[int]) -> int:
    return int(statistics.median(values)) if values else 0


def summary(runs: list[RunResult]) -> dict[str, Any]:
    return {"passes": sum(r.passed for r in runs), "runs": len(runs), "steps": [r.steps for r in runs],
            "limit_hit": sum(r.limit_hit for r in runs), "refused": sum(len(r.refused) for r in runs),
            "repeats": sum(r.repeats for r in runs), "errors": sum(r.error is not None for r in runs),
            "latency_ms_median": _median([r.latency_ms for r in runs]),
            "steps_to_write": [r.steps_to_write for r in runs if r.steps_to_write is not None or r.case_id in actions()]}


def actions() -> set[str]:
    return {c["id"] for c in load() if c["expect"] == "action"}


def total(results: dict[str, list[RunResult]]) -> dict[str, Any]:
    """The summary over every run, but `limit_hit` and `steps` over the cases that are not `action` ones, and
    `steps_to_write` the median over the `action` runs that wrote (0 when none did)."""
    everything = [r for rs in results.values() for r in rs]
    acting = actions()
    measured = [r for r in everything if r.case_id not in acting]
    wrote = [r.steps_to_write for r in everything if r.steps_to_write is not None]
    return {**summary(everything), "steps": [r.steps for r in measured], "limit_hit": sum(r.limit_hit for r in measured),
            "steps_to_write": _median(wrote)}


def to_json(results: dict[str, list[RunResult]]) -> str:
    """Every run of every case, a summary per case and the total."""
    expects = {c["id"]: (c["channel"], c["expect"]) for c in load()}
    cases = [{"id": cid, "channel": expects[cid][0], "expect": expects[cid][1], "summary": summary(rs),
              "runs": [asdict(r) for r in rs]} for cid, rs in results.items()]
    return json.dumps({"total": total(results), "cases": cases}, indent=2)


def render(results: dict[str, list[RunResult]]) -> str:
    """One row per case, a total row, then each run's tool sequence and input tokens per step."""
    expects = {c["id"]: (c["channel"], c["expect"]) for c in load()}
    head = f"{'case':22} {'ch':5} {'expect':12} {'pass':>5} {'steps':>8} {'limit':>5} {'refused':>7} {'write':>7} {'repeat':>6} {'ms':>6}"
    rows = [head]
    for cid, rs in results.items():
        s = summary(rs)
        rows.append(f"{cid:22} {expects[cid][0]:5} {expects[cid][1]:12} {s['passes']}/{s['runs']:<3} "
                    f"{','.join(map(str, s['steps'])):>8} {s['limit_hit']:>5} {s['refused']:>7} {','.join(str(w) for w in s['steps_to_write']) or '-':>7} {s['repeats']:>6} "
                    f"{s['latency_ms_median']:>6}")
    t = total(results)
    rows.append(f"{'TOTAL':22} {'':5} {'':12} {t['passes']}/{t['runs']:<3} {'':>8} {t['limit_hit']:>5} "
                f"{t['refused']:>7} {t['steps_to_write']:>7} {t['repeats']:>6} {t['latency_ms_median']:>6}")
    for cid, rs in results.items():
        for i, r in enumerate(rs, 1):
            rows.append(f"  {cid}#{i}: {'>'.join(r.tools) or '-'} | tokens {list(r.tokens)}"
                        + (f" | {r.error}" if r.error else "") + (f" | would have called {list(r.refused)}" if r.refused else ""))
    return "\n".join(rows)
