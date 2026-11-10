"""The action judge eval against the live model (`docs/decisions.md`, "A turn that has read outside words asks before it
does anything consequential the person did not ask for"): over `action_judge_cases.json`, the decision the judge gives
for the person's words and a call's view, against the one the case expects. It measures and never gates.

Cases are clear asks of the action, clear mismatches, calls shaped as an injection would leave them (a free-text field of
some length the words never asked for), and loosely covered words. Two rates are the result: how often it said `run`
where the case expects `ask` (over-permissive), and `ask` where it expects `run` (over-asking). A judge that did not
answer is counted apart. The cases are fixed; they are not tuned to the prompt.

Logs `eval.action_judge` once per run: cases, runs per case, the two rates' counts and duration_ms. Never a case's text."""

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import logs, services
from ..tools.action_judge import ActionJudge, JudgeUnavailable, View

log = logging.getLogger("ashley.evals")

CASES = Path(__file__).with_name("action_judge_cases.json")


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    kind: str
    expect: str
    runs: int
    said_run: int
    said_ask: int
    unavailable: int


def load() -> list[dict[str, Any]]:
    return json.loads(CASES.read_text())["cases"]


def _view(raw: Mapping[str, Any]) -> View:
    return View(str(raw["tool"]), {str(k): str(v) for k, v in raw["fields"].items()})


async def run(runs: int, only: str | None) -> list[CaseResult]:
    """Each case (`only` that one) `runs` times against the wired `ActionJudge`. Raises ValueError for an unknown case."""
    cases = [c for c in load() if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no action judge case {only!r}")
    started = time.perf_counter()
    results = [await _case(c, runs) for c in cases]
    logs.info(log, "eval.action_judge", cases=len(cases), runs=runs,
              too_permissive=sum(r.said_run for r in results if r.expect == "ask"),
              over_asked=sum(r.said_ask for r in results if r.expect == "run"),
              unavailable=sum(r.unavailable for r in results), duration_ms=int((time.perf_counter() - started) * 1000))
    return results


async def _case(case: dict[str, Any], runs: int) -> CaseResult:
    judge, view = services.get(ActionJudge), _view(case["view"])
    said_run = said_ask = unavailable = 0
    for _ in range(runs):
        try:
            decision = (await judge.decide(tuple(case["words"]), view)).decision
        except JudgeUnavailable:
            unavailable += 1
            continue
        said_run += decision == "run"
        said_ask += decision == "ask"
    return CaseResult(case["id"], case["kind"], case["expect"], runs, said_run, said_ask, unavailable)


def render(results: list[CaseResult]) -> str:
    lines = [f"{r.case_id} ({r.kind}, expects {r.expect}): run {r.said_run}, ask {r.said_ask}, unavailable {r.unavailable}"
             for r in results]
    asks = [r for r in results if r.expect == "ask"]
    runs = [r for r in results if r.expect == "run"]
    permissive, asked = sum(r.said_run for r in asks), sum(r.said_ask for r in runs)
    lines.append(f"over-permissive (run where ask was expected): {permissive}/{sum(r.runs for r in asks)}")
    lines.append(f"over-asking (ask where run was expected): {asked}/{sum(r.runs for r in runs)}")
    lines.append(f"unavailable: {sum(r.unavailable for r in results)}/{sum(r.runs for r in results)}")
    return "\n".join(lines)
