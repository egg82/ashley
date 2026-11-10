"""The reply eval against the live model: whether her reply sets `Reply.owed` exactly when someone asks for something a
tool source that is out of reach would have done and it is still wanted later, and not for a statement, a question,
an ask that only makes sense now, or a source that answered. Over `reply_owed_cases.json`: a case's `unreachable` is the
sources the turn's catalogue found out of reach, `owed` the source key she must set or `null`. The prompt is her real
persona for a chat with a known speaker; grading is the field itself. Nothing is judged by a model.

Logs `eval.reply_owed` once per run: cases, runs per case, passes and duration_ms. Never a case's text or the model's."""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import logs, services
from ..inference.inference import Inference
from ..inference.model import Message, Prompt
from ..inference.reply import Reply
from ..people.model import Household, Person
from ..persona import persona

log = logging.getLogger("ashley.evals")

CASES = Path(__file__).parent / "reply_owed_cases.json"
ALANA = Person(1, 1, "Alana")
HOUSEHOLD = Household(1, "eval", "UTC", "", (ALANA,))
GUIDANCE = "Use the tools to read and change the house, its lists and its reminders."


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    expected: str | None
    passed: int
    runs: int


def load() -> list[dict[str, Any]]:
    return json.loads(CASES.read_text())["cases"]


async def run(runs: int, only: str | None) -> list[CaseResult]:
    """Each case (`only` that one) `runs` times. Needs `Inference` wired. Raises ValueError for an unknown case, and
    the inference errors from the model."""
    cases = [c for c in load() if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no owed case {only!r}")
    started = time.perf_counter()
    results = [await _case(c, runs) for c in cases]
    logs.info(log, "eval.reply_owed", cases=len(cases), runs=runs, passes=sum(r.passed for r in results),
              duration_ms=int((time.perf_counter() - started) * 1000))
    return results


async def _case(case: dict[str, Any], runs: int) -> CaseResult:
    system = persona.system("chat", persona.Context(
        now=datetime.now(UTC), household=HOUSEHOLD, speaker=ALANA, home=None, place=None, tool_instructions=GUIDANCE,
        tools_reachable=True, tools_unreachable=tuple(case["unreachable"])))
    said = tuple(Message(a, f"Alana: {t}" if a == "person" else t) for a, t in case["said"])
    passed = 0
    for _ in range(runs):
        got = await services.get(Inference).step("chat", Prompt(system, said, (), "auto"), Reply)
        passed += isinstance(got, Reply) and got.owed == case["owed"]
    return CaseResult(case["id"], case["owed"], passed, runs)


def render(results: list[CaseResult]) -> str:
    lines = [f"{'PASS' if r.passed == r.runs else 'FAIL'} {r.case_id}: {r.passed}/{r.runs} (want {r.expected or 'null'})"
             for r in results]
    return "\n".join([*lines, f"total {sum(r.passed for r in results)}/{sum(r.runs for r in results)}"])
