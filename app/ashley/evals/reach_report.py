"""The reach eval's table and JSON: per case and in total, so a run with groups cut can be diffed against today's."""

import json
import statistics
from collections import Counter
from dataclasses import asdict
from typing import Any

from .reach import RunResult, lacking, load


def _median(values: list[int]) -> int:
    return int(statistics.median(values)) if values else 0


def summary(runs: list[RunResult]) -> dict[str, Any]:
    """Passes, how often each extra group was called and each group loaded, steps, limit hits, the median of each run's first and of every step's input
    tokens, errors and the names no catalogue held."""
    steps = [t for r in runs for t in r.tokens]
    return {"passes": sum(r.passed for r in runs), "runs": len(runs), "steps": [r.steps for r in runs],
            "extra": dict(Counter(g for r in runs for g in r.extra)),
            "loaded": dict(Counter(g for r in runs for g in r.loaded)),
            "missing": dict(Counter(m for r in runs for m in r.missing)),
            "unoffered": sorted({u for r in runs for u in r.unoffered}),
            "limit_hit": sum(r.limit_hit for r in runs), "refused": sum(len(r.refused) for r in runs),
            "errors": sum(r.error is not None for r in runs),
            "tokens_first_median": _median([r.tokens[0] for r in runs if r.tokens]), "tokens_step_median": _median(steps)}


def wants_nothing(case: dict[str, Any]) -> bool:
    return not case["groups"] and not case["tools"] and "any_of" not in case


def total(results: dict[str, list[RunResult]]) -> dict[str, Any]:
    """The summary over every run, and `false_positives`: runs of a no-tool ask that called a tool."""
    nothing = {c["id"] for c in load() if wants_nothing(c)}
    everything = [r for rs in results.values() for r in rs]
    return {**summary(everything), "false_positives": sum(bool(r.tools) for r in everything if r.case_id in nothing),
            "no_tool_runs": sum(r.case_id in nothing for r in everything)}


def rescore(saved: dict[str, Any]) -> str:
    """A saved `--json` run scored again against today's cases, with no model call: a pass per case, then the total beside the
    saved one. A saved case no longer in the file is skipped. Uses each run's recorded tools and groups reached."""
    cases = {c["id"]: c for c in load()}
    rows: list[str] = []
    passed, runs, was = 0, 0, 0
    for entry in saved["cases"]:
        case = cases.get(entry["id"])
        if case is None:
            continue
        ok = [not r["error"] and (not r["tools"] if wants_nothing(case) else not lacking(case, r["tools"], r["groups"]))
              for r in entry["runs"]]
        passed, runs, was = passed + sum(ok), runs + len(ok), was + sum(r["passed"] for r in entry["runs"])
        rows.append(f"{entry['id']:26} {sum(ok)}/{len(ok)}" + ("" if sum(ok) == entry["summary"]["passes"] else f"  (was {entry['summary']['passes']})"))
    return "\n".join([*rows, f"{'TOTAL':26} {passed}/{runs}  (was {was}/{runs})"])


def to_json(results: dict[str, list[RunResult]], variant: str = "none") -> str:
    """The prompt `variant`'s label, every run of every case, a summary per case and the total."""
    cases = [{"id": cid, "summary": summary(rs), "runs": [asdict(r) for r in rs]} for cid, rs in results.items()]
    return json.dumps({"variant": variant, "total": total(results), "cases": cases}, indent=2)


def render(results: dict[str, list[RunResult]], variant: str = "none") -> str:
    """The prompt `variant`'s label, one row per case, a total row, then each run's tool sequence, extra groups and input
    tokens per step."""
    head = f"{'case':26} {'pass':>5} {'steps':>8} {'first':>7} {'step':>7}  {'extra':22} loaded"
    rows = [f"variant: {variant}", head]
    for cid, rs in results.items():
        s = summary(rs)
        rows.append(f"{cid:26} {s['passes']}/{s['runs']:<3} {','.join(map(str, s['steps'])):>8} "
                    f"{s['tokens_first_median']:>7} {s['tokens_step_median']:>7}  {','.join(s['extra']) or '-':22} "
                    f"{','.join(s['loaded']) or '-'}")
    t = total(results)
    rows.append(f"{'TOTAL':26} {t['passes']}/{t['runs']:<3} {'':>8} {t['tokens_first_median']:>7} {t['tokens_step_median']:>7}  "
                f"{sum(t['extra'].values())} extra, {t['false_positives']}/{t['no_tool_runs']} no-tool runs called a tool")
    for cid, rs in results.items():
        for i, r in enumerate(rs, 1):
            rows.append(f"  {cid}#{i}: {'>'.join(r.tools) or '-'} | tokens {list(r.tokens)}"
                        + (f" | loaded {list(r.loaded)}" if r.loaded else "")
                        + (f" | missing {list(r.missing)}" if r.missing else "")
                        + (f" | unoffered {list(r.unoffered)}" if r.unoffered else "")
                        + (f" | {r.error}" if r.error else ""))
    return "\n".join(rows)
