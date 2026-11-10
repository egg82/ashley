"""The bench-act eval: what she does on a bench, graded by step type and tool names, never by her words (`docs/decisions.md`,
"Her behaviour is measured by what she did"). Each case in `bench_act_cases.json` runs through the real loop
(`channels.tool_loop.answer`, `resume`) with her real bench and move_page tools reading a captured bench
(`bench_act_fakes`): reads come from the capture, a change is noted and not applied, `bench_run` returns the captured run,
and a fake clock moves per model step so the deadline, holds and resumes are exercised. A case expects, in `expect`:
`bench_run_min`, `model_changes_min` (changes on the model piece), `changes_min`/`changes_max` (changes on the bench,
`move_page` apart), `closed`, `answers`, `no_deadline_close`, `windows_taken`, `rounds_after_resume_min` (model steps under tool choice auto after the resume), `held_max`,
`moved_to`, `no_taint_before_outside_read`. Live it measures and never gates; `--scripted` swaps the model for a scripted
policy that checks the harness and the loop's mechanics only.

`--clock age`, `--windows 0`, `--hold 6`, `--no-now` reproduce the behaviour before the bench-gap fixes where the
fix is a setting. Logs `eval.bench_act` once per run of the eval: cases, runs, passes and duration_ms."""

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import logs, services
from ..channels import limits as limits_config
from ..channels import tool_loop
from ..channels.limits import Kind, Limits
from ..channels.tool_loop import Answer, Arrived, Held, Progress
from ..inference.inference import Inference, InferenceUnavailable
from ..inference.model import Message, SystemPrompt, ToolCall, ToolResult, ToolSpec
from ..people.model import Household, Person
from ..persona import persona
from ..tools import bench_run
from ..tools.bench_tools import BenchTools
from ..tools.composite import CompositeTools
from ..tools.move_page import NAME as MOVE_PAGE_NAME, MovePageTools
from ..tools.tools import Catalogue, Tools
from ..tools import bench_capture
from ..tools.bench_capture import Capture
from .bench_act_fakes import Clock, Clocked, Recorded, Recorder
from .bench_act_policy import Scripted
from .house_guard import RecordingInference

log = logging.getLogger("ashley.evals")
CASES = Path(__file__).parent / "bench_act_cases.json"
CAPTURE = Path(__file__).parent / "bench_act_capture.json"
MODEL_PIECE = 6


@dataclass(frozen=True)
class Options:
    scripted: bool = False
    clock: str = "work"
    windows: int | None = None
    hold: float | None = None
    now: bool = True


@dataclass(frozen=True)
class Result:
    case_id: str
    passed: bool
    metrics: dict[str, object]


def load() -> list[dict[str, Any]]:
    return json.loads(CASES.read_text())["cases"]


class _RunSpec(Tools):
    """Offers `bench_run` so the scripted bench has it; `Recorded` answers the call."""

    async def catalogue(self) -> Catalogue:
        return Catalogue(bench_run.specs(("build123d",)), None)

    async def call(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError


def _bench_source(capture: Capture) -> Tools:
    return CompositeTools({"bench": BenchTools(1, 1, capture.bench.id), "run": _RunSpec()})


async def run(runs: int, only: str | None, options: Options = Options()) -> list[Result]:
    """Each case (`only` that one) `runs` times; the live `Inference` is the model unless `options.scripted`. Raises
    ValueError for an unknown case."""
    cases = [c for c in load() if only is None or c["id"] == only]
    if not cases:
        raise ValueError(f"no bench-act case {only!r}")
    started = time.perf_counter()
    live = None if options.scripted else services.get(Inference)
    results = [await _graded(c, options, live) for c in cases for _ in range(runs)]
    logs.info(log, "eval.bench_act", cases=len(cases), runs=runs, passes=sum(r.passed for r in results),
              duration_ms=int((time.perf_counter() - started) * 1000))
    return results


async def _graded(case: dict[str, Any], options: Options, live: Inference | None) -> Result:
    metrics = await _one(case, options, live)
    return Result(case["id"], passes(case["expect"], metrics), metrics)


async def _one(case: dict[str, Any], options: Options, live: Inference | None) -> dict[str, object]:
    capture = bench_capture.load(CAPTURE)
    capture = capture.household_only() if case.get("household_only") else capture
    bench_capture.install(capture)
    clock = Clock()
    inner = RecordingInference(Scripted(case["policy"]) if live is None else live)
    services.register(Inference, Clocked(inner, clock, case.get("step_s", 20), case.get("fail_at_step")))
    chat = case["scene"] == "chat"
    source = Recorded(CompositeTools({"page": MovePageTools(1, 1)}) if chat else _bench_source(capture), capture)
    return await _play(case, options, source, clock, inner)


ANN = Person(1, 1, "Ann")
HOUSEHOLD = Household(1, "eval", "UTC", "", (ANN,))


def _system(kind: Kind, catalogue: Catalogue, options: Options) -> Mapping[str, SystemPrompt]:
    return persona.system(kind, persona.Context(
        now=datetime.now(UTC), household=HOUSEHOLD, speaker=ANN, home=None, place=None,
        tool_instructions=catalogue.instructions, tools_reachable=True, tools_now=catalogue.now if options.now else None))


def _moved(system: Mapping[str, SystemPrompt], catalogue: Catalogue, options: Options) -> Mapping[str, SystemPrompt]:
    more = "\n\n".join(t for t in (catalogue.instructions, catalogue.now if options.now else None) if t)
    return {k: replace(v, moment=f"{v.moment}\n\n{more}") for k, v in system.items()}


def _limits(kind: Kind, options: Options) -> Limits:
    base = limits_config.load()[kind]
    return replace(base, **{k: v for k, v in (("windows", options.windows), ("hold_after_s", options.hold)) if v is not None})


async def _play(case: dict[str, Any], options: Options, source: Recorded, clock: Clock,
                steps_taken: RecordingInference) -> dict[str, object]:
    kind: Kind = "chat" if case["scene"] == "chat" else "brainstorm"
    catalogue = await source.catalogue()
    system = _system(kind, catalogue, options)
    history = (*(Message(a, t) for a, t in case["said"]), Message("person", case["ask"]))
    steps, held = Recorder(), 0
    after: int | None = None
    limits = _limits(kind, options)
    arrive = _arrival(source, options)
    began = clock()
    try:
        got = await tool_loop.answer(kind, system, history, catalogue.specs, limits, 1, True, source, began, clock,
                                     steps, arrive)
        while isinstance(got, Held):
            held += 1
            got = await tool_loop.resume(got, kind, system, catalogue.specs, limits, 1, source, began, clock, steps, arrive)
    except InferenceUnavailable:
        before = len(steps_taken.steps)
        got = await _resumed(case, options, source, clock, steps, kind, system, catalogue.specs, limits, arrive)
        after = sum(s.choice == "auto" for s in steps_taken.steps[before:])
    return _metrics(got, after, source, steps, held, clock() - began)


async def _resumed(case: dict[str, Any], options: Options, source: Recorded, clock: Clock, steps: Recorder, kind: Kind,
                   system: Mapping[str, SystemPrompt], specs: tuple[ToolSpec, ...], limits: Limits,
                   arrive: tool_loop.Arrive) -> Answer:
    waited = case["resume"]
    spent = waited["worked_s"] if options.clock == "work" else waited["age_s"]
    progress = Progress(steps.entries, steps.rounds, steps.calls, steps.asked_now, steps.done)
    return await tool_loop.resumed(progress, kind, system, specs, limits, 1, source, True, clock() - spent, clock, steps,
                                   arrive)


def _arrival(source: Recorded, options: Options) -> tool_loop.Arrive:
    state = {"done": False}

    async def arrive(system: Mapping[str, SystemPrompt]) -> Arrived | None:
        if source.moved_to is None or state["done"]:
            return None
        state["done"] = True
        bench = _bench_source(source.capture)
        source.inner = bench
        got = await bench.catalogue()
        return Arrived(got.specs, _moved(system, got, options), _limits("brainstorm", options), "brainstorm")

    return arrive


def _metrics(got: Answer | Held, after: int | None, source: Recorded, steps: Recorder, held: int,
             seconds: float) -> dict[str, object]:
    assert isinstance(got, Answer)
    bench = [c for c in source.changes if c.name != MOVE_PAGE_NAME]
    return {"changes": got.changes, "bench_changes": len(bench), "bench_run": source.calls_named(bench_run.RUN),
            "model_changes": sum(c.arguments.get("piece_id") == MODEL_PIECE for c in bench), "closed": got.closed,
            "answers": got.reply.answers, "held": held, "windows_taken": steps.taken, "moved_to": source.moved_to,
            "rounds_after_resume": after, "tainted_by": steps.tainted_by, "seconds": round(seconds)}


def passes(expect: dict[str, Any], m: dict[str, object]) -> bool:
    """Whether the measured run meets each expectation; a key the case does not name is not asked."""
    asked: dict[str, Callable[[Any], bool]] = {
        "bench_run_min": lambda v: _num(m["bench_run"]) >= v,
        "model_changes_min": lambda v: _num(m["model_changes"]) >= v,
        "changes_min": lambda v: _num(m["bench_changes"]) >= v,
        "changes_max": lambda v: _num(m["changes"]) <= v,
        "closed": lambda v: m["closed"] == v,
        "answers": lambda v: m["answers"] is v,
        "no_deadline_close": lambda v: (m["closed"] != "deadline") is v,
        "windows_taken": lambda v: m["windows_taken"] == v,
        "rounds_after_resume_min": lambda v: _num(m["rounds_after_resume"]) >= v,
        "held_max": lambda v: _num(m["held"]) <= v,
        "moved_to": lambda v: m["moved_to"] == v,
        "no_taint_before_outside_read": lambda v: (m["tainted_by"] is None) is v,
    }
    return all(asked[k](v) for k, v in expect.items())


def _num(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else -1.0


def render(results: list[Result]) -> str:
    ids = list(dict.fromkeys(r.case_id for r in results))
    lines: list[str] = []
    for case_id in ids:
        mine = [r for r in results if r.case_id == case_id]
        last = mine[-1].metrics
        lines.append(f"{case_id}: {sum(r.passed for r in mine)}/{len(mine)} pass; last run "
                     + " ".join(f"{k}={v}" for k, v in last.items()))
    return "\n".join([*lines, f"total {sum(r.passed for r in results)}/{len(results)}"])
