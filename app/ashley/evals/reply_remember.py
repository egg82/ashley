"""The reply eval against the live model: whether her reply sets `Reply.memory` exactly when someone asks her to act
on memory, and with the right action and fact ids, over `reply_remember_cases.json`. A case's `act` is `null` (she sets
nothing) or `{"action", "facts"}`, the facts compared as a set. The prompt is her real persona for a chat with a known
speaker and no tools, with a case's `remembered` facts (`[id, text]`, the household's) as what she remembers; grading is
the field itself. Nothing is judged by a model.

Logs `eval.reply_remember` once per run: cases, runs per case, passes and duration_ms. Never a case's text or the
model's."""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import services
from ..inference.inference import Inference
from ..inference.model import Message, Prompt
from ..inference.reply import Reply
from ..memory.model import Fact, Recalled
from ..people.model import Household, Person
from ..persona import persona
from .. import logs

log = logging.getLogger("ashley.evals")

CASES = Path(__file__).parent / "reply_remember_cases.json"
ALANA = Person(1, 1, "Alana")
HOUSEHOLD = Household(1, "eval", "UTC", "", (ALANA,))


Act = tuple[str, frozenset[int]]
"""An action and the fact ids it names."""


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    expected: Act | None
    passed: int
    runs: int


def load() -> list[dict[str, Any]]:
    return json.loads(CASES.read_text())["cases"]


async def run(runs: int, only: str | None) -> list[CaseResult]:
    """Each case (`only` that one) `runs` times. Needs `Inference` wired. Raises ValueError for an unknown case, and
    the inference errors from the model."""
    cases = [c for c in load() if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no reply case {only!r}")
    started = time.perf_counter()
    results = [await _case(c, runs) for c in cases]
    logs.info(log, "eval.reply_remember", cases=len(cases), runs=runs, passes=sum(r.passed for r in results),
              duration_ms=int((time.perf_counter() - started) * 1000))
    return results


async def _case(case: dict[str, Any], runs: int) -> CaseResult:
    system = persona.system("chat", persona.Context(
        now=datetime.now(UTC), household=HOUSEHOLD, speaker=ALANA, home=None, place=None, tool_instructions=None,
        tools_reachable=True, remembered=tuple(_recalled(i, t) for i, t in case.get("remembered", ()))))
    said = tuple(Message(a, f"Alana: {t}" if a == "person" else t) for a, t in case["said"])
    wanted = _wanted(case["act"])
    passed = 0
    for _ in range(runs):
        got = await services.get(Inference).step("chat", Prompt(system, said, (), "auto"), Reply)
        passed += isinstance(got, Reply) and _asked(got) == wanted
    return CaseResult(case["id"], wanted, passed, runs)


def _wanted(act: dict[str, Any] | None) -> Act | None:
    return None if act is None else (act["action"], frozenset(act["facts"]))


def _asked(reply: Reply) -> Act | None:
    return None if reply.memory is None else (reply.memory.action, frozenset(reply.memory.facts))


def _recalled(fact_id: int, text: str) -> Recalled:
    return Recalled(Fact(fact_id, HOUSEHOLD.id, None, None, "shared", "other", False, text, 1,
                         datetime(2026, 1, 1, tzinfo=UTC), None, None), True)


def _show(act: Act | None) -> str:
    return "no act" if act is None else f"{act[0]} {sorted(act[1])}"


def render(results: list[CaseResult]) -> str:
    lines = [f"{'PASS' if r.passed == r.runs else 'FAIL'} {r.case_id}: {r.passed}/{r.runs} (want {_show(r.expected)})"
             for r in results]
    return "\n".join([*lines, f"total {sum(r.passed for r in results)}/{sum(r.runs for r in results)}"])
