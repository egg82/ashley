"""The house eval against the live model and the live house: how she uses the house's tools. Each case in
`house_cases.json` is asked through her real turn loop (`channels.respond`), `runs` times, with every tool call that
is not on the read allow-list (`house_reads.json`) kept from Home Assistant and answered as done, whatever the case
expects (`house_guard.GuardedTools`). A case expects `read_only` (any refused call fails it), `action` (a call to one of
its `tools` whose arguments name its `target` passes; the call is still kept from the house, and reported as one she would have
made) or `unknown_name` (a thing the house does not have: any refused call fails it; whether she said so is not graded,
and her words are not kept).

Per run: steps (rounds of tool calls), whether the step limit was reached, the tool names in order, her main calls'
input tokens per step from the spend ledger, end-to-end latency, refused calls, identical repeated calls and, on an
`action` case, the round the expected write was first asked for (`steps_to_write`). An `action` case's steps and step
limit are not measured: it ends when the write is answered as done and she checks a house that never changed, so the
totals leave them out. Logs
`eval.house` once per run of the eval: cases, runs, passes, refused calls and duration_ms. Never a case's reply, a
tool's arguments or results."""

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import logs, services
from ..channels.model import Inbound
from ..channels.respond import respond
from ..home_assistant.homes import Homes
from ..inference.inference import Inference
from ..tools.everyday import Everyday
from ..tools.tools import Tools
from .house_guard import Attempt, GuardedTools, RecordingInference, Step
from .house_readonly import ReadOnlyHomes

log = logging.getLogger("ashley.evals")

CASES = Path(__file__).parent / "house_cases.json"
READS = Path(__file__).parent / "house_reads.json"


@dataclass(frozen=True)
class Billed:
    """One of her main calls as the spend ledger has it: prompt tokens (fresh, cache read and cache write) and who answered."""

    tokens: int
    provider: str
    model: str


Ledger = Callable[[int, str], Awaitable[list[Billed]]]
"""The ledger rows of a conversation's calls for a task, oldest first."""


@dataclass(frozen=True)
class Seat:
    """Who asks: a household and a person in it."""

    household_id: int
    person_id: int


@dataclass(frozen=True)
class RunResult:
    case_id: str
    passed: bool
    steps: int
    limit_hit: bool
    tools: tuple[str, ...]
    tokens: tuple[int, ...]
    models: tuple[str, ...]
    latency_ms: int
    refused: tuple[str, ...]
    steps_to_write: int | None
    repeats: int
    error: str | None


def load() -> list[dict[str, Any]]:
    return json.loads(CASES.read_text())["cases"]


def reads() -> frozenset[str]:
    return frozenset(json.loads(READS.read_text())["read"])


def inbound(case: dict[str, Any], seat: Seat) -> Inbound:
    """The ask on its channel: `chat` is the owner's web chat, `voice` a shared kitchen satellite."""
    thread = f"house-eval-{uuid.uuid4()}"
    if case["channel"] == "voice":
        return Inbound(seat.household_id, thread, case["ask"], "command", "spoken", "present", None, True, "kitchen",
                       "voice", remembers=False, taint=None)
    return Inbound(seat.household_id, thread, case["ask"], "chat", "text", "owner", seat.person_id, False, None, "web",
                   remembers=False, taint=None)


def is_expected_write(case: dict[str, Any], name: str, arguments: str) -> bool:
    return name in case["tools"] and case["target"].lower() in arguments.lower()


def passes(case: dict[str, Any], refused: list[Attempt]) -> bool:
    if case["expect"] != "action":
        return not refused
    return any(is_expected_write(case, a.name, a.arguments) for a in refused)


def steps_to_write(case: dict[str, Any], steps: list[Step]) -> int | None:
    """For an `action` case, the 1-based tool round in which the expected write was first asked for; None if never
    (and for every other kind of case)."""
    if case["expect"] != "action":
        return None
    rounds = [s for s in steps if s.asked]
    for i, s in enumerate(rounds, 1):
        if any(is_expected_write(case, c.name, json.dumps(c.arguments, sort_keys=True, default=str)) for c in s.asked):
            return i
    return None


def repeats(steps: list[Step]) -> int:
    """How many calls repeated an earlier call of the reply: same tool, same arguments."""
    seen: set[tuple[str, str]] = set()
    count = 0
    for call in (c for s in steps for c in s.asked):
        key = (call.name, json.dumps(call.arguments, sort_keys=True, default=str))
        count += key in seen
        seen.add(key)
    return count


async def one(case: dict[str, Any], seat: Seat, ledger: Ledger, guard: GuardedTools,
              recorder: RecordingInference) -> RunResult:
    """One ask. A turn that raises is a failed run naming the exception type."""
    guard.refused.clear()
    guard.ran.clear()
    recorder.steps.clear()
    ask = inbound(case, seat)
    started = time.perf_counter()
    error, conversation = None, None
    try:
        conversation = (await respond(ask)).conversation_id
    except Exception as e:
        error = type(e).__name__
    latency = int((time.perf_counter() - started) * 1000)
    steps = [s for s in recorder.steps if s.task == ask.kind]
    billed = [] if conversation is None else await ledger(conversation, ask.kind)
    names = tuple(c.name for s in steps for c in s.asked)
    return RunResult(case["id"], error is None and passes(case, guard.refused), sum(bool(s.asked) for s in steps),
                     any(s.choice == "none" for s in steps), names, tuple(b.tokens for b in billed),
                     tuple(sorted({f"{b.provider}/{b.model}" for b in billed})), latency,
                     tuple(a.name for a in guard.refused),
                     steps_to_write(case, steps), repeats(steps), error)


async def run(runs: int, only: str | None, seat: Seat, ledger: Ledger) -> dict[str, list[RunResult]]:
    """Each case (`only` that one) `runs` times, in order, through the wired services with the seat's household's
    everyday tools guarded, the House under her per-turn tools read-only (`house_readonly`) and `Inference` recorded for the run. Raises ValueError for an unknown case; ToolsUnavailable
    when which house the household has cannot be read."""
    cases = [c for c in load() if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no house case {only!r}")
    real_everyday, real_inference, real_homes = services.get(Everyday), services.get(Inference), services.get(Homes)
    guard = GuardedTools(await real_everyday.of(seat.household_id), reads())
    recorder = RecordingInference(real_inference)
    services.register(Everyday, _Guarded(guard))
    services.register(Homes, ReadOnlyHomes(real_homes, guard.refused))
    services.register(Inference, recorder)
    started = time.perf_counter()
    try:
        out = {c["id"]: [await one(c, seat, ledger, guard, recorder) for _ in range(runs)] for c in cases}
    finally:
        services.register(Everyday, real_everyday)
        services.register(Homes, real_homes)
        services.register(Inference, real_inference)
    logs.info(log, "eval.house", cases=len(cases), runs=runs, passes=sum(r.passed for rs in out.values() for r in rs),
              refused=sum(len(r.refused) for rs in out.values() for r in rs),
              duration_ms=int((time.perf_counter() - started) * 1000))
    return out


class _Guarded(Everyday):
    """Every household's everyday tools are the guard, for the run."""

    def __init__(self, guard: Tools) -> None:
        self._guard = guard

    async def of(self, household_id: int) -> Tools:
        return self._guard
