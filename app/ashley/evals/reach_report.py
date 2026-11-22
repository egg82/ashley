"""The reach eval's table and JSON: per case and in total, so a run with groups cut can be diffed against today's."""

import json
import statistics
from collections import Counter
from dataclasses import asdict
from typing import Any

from .reach import RunResult, load


def _median(values: list[int]) -> int:
    return int(statistics.median(values)) if values else 0


def summary(runs: list[RunResult]) -> dict[str, Any]:
    """Passes, how often each extra group was called, steps, limit hits, the median of each run's first and of every step's input
    tokens, errors and the names no catalogue held."""
    steps = [t for r in runs for t in r.tokens]
    return {"passes": sum(r.passed for r in runs), "runs": len(runs), "steps": [r.steps for r in runs],
            "extra": dict(Counter(g for r in runs for g in r.extra)),
            "missing": dict(Counter(m for r in runs for m in r.missing)),
            "unoffered": sorted({u for r in runs for u in r.unoffered}),
            "limit_hit": sum(r.limit_hit for r in runs), "refused": sum(len(r.refused) for r in runs),
            "errors": sum(r.error is not None for r in runs),
            "tokens_first_median": _median([r.tokens[0] for r in runs if r.tokens]), "tokens_step_median": _median(steps)}


def wants_nothing(case: dict[str, Any]) -> bool:
    return not case["groups"] and not case["tools"]


def total(results: dict[str, list[RunResult]]) -> dict[str, Any]:
    """The summary over every run, and `false_positives`: runs of a no-tool ask that called a tool."""
    nothing = {c["id"] for c in load() if wants_nothing(c)}
    everything = [r for rs in results.values() for r in rs]
    return {**summary(everything), "false_positives": sum(bool(r.tools) for r in everything if r.case_id in nothing),
            "no_tool_runs": sum(r.case_id in nothing for r in everything)}


def to_json(results: dict[str, list[RunResult]], variant: str = "none") -> str:
    """The prompt `variant`'s label, every run of every case, a summary per case and the total."""
    cases = [{"id": cid, "summary": summary(rs), "runs": [asdict(r) for r in rs]} for cid, rs in results.items()]
    return json.dumps({"variant": variant, "total": total(results), "cases": cases}, indent=2)


def render(results: dict[str, list[RunResult]], variant: str = "none") -> str:
    """The prompt `variant`'s label, one row per case, a total row, then each run's tool sequence, extra groups and input
    tokens per step."""
    head = f"{'case':26} {'pass':>5} {'steps':>8} {'first':>7} {'step':>7}  extra"
    rows = [f"variant: {variant}", head]
    for cid, rs in results.items():
        s = summary(rs)
        rows.append(f"{cid:26} {s['passes']}/{s['runs']:<3} {','.join(map(str, s['steps'])):>8} "
                    f"{s['tokens_first_median']:>7} {s['tokens_step_median']:>7}  {','.join(s['extra']) or '-'}")
    t = total(results)
    rows.append(f"{'TOTAL':26} {t['passes']}/{t['runs']:<3} {'':>8} {t['tokens_first_median']:>7} {t['tokens_step_median']:>7}  "
                f"{sum(t['extra'].values())} extra, {t['false_positives']}/{t['no_tool_runs']} no-tool runs called a tool")
    for cid, rs in results.items():
        for i, r in enumerate(rs, 1):
            rows.append(f"  {cid}#{i}: {'>'.join(r.tools) or '-'} | tokens {list(r.tokens)}"
                        + (f" | missing {list(r.missing)}" if r.missing else "")
                        + (f" | unoffered {list(r.unoffered)}" if r.unoffered else "")
                        + (f" | {r.error}" if r.error else ""))
    return "\n".join(rows)
