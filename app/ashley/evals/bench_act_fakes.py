"""What the bench-act eval stands on: a Workshop serving the captured bench (`bench_act_capture.json`), her real bench
and move_page tools reading from it, `Recorded` in front of them so a change is noted and never applied and `bench_run`
answers with the captured run, an inference that moves a fake clock and can fail at a step, and a `Recorder` of the
turn's progress for the resume cases."""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel

from ..channels.tool_loop import Steps
from ..inference.inference import Inference, InferenceUnavailable
from ..inference.model import Entry, Prompt, Task, ToolCall, ToolCalls, ToolResult, ToolSpec
from ..tools.bench_capture import OUTSIDE_KINDS, Capture
from ..tools.bench_run import RUN
from ..tools.move_page import NAME as MOVE
from ..tools.tools import Catalogue, Tools
from .house_guard import RecordingInference

T = TypeVar("T", bound=BaseModel)
READS = ("bench_read", "bench_read_piece", "bench_shelf")


@dataclass
class Recorded(Tools):
    """`inner` for reads. A change is noted in `changes` and answered done; `bench_run` answers with the captured run;
    `move_page` notes where the page went. An outside-kind piece read whole is answered from the capture, outside."""

    inner: Tools
    capture: Capture
    changes: list[ToolCall] = field(default_factory=list[ToolCall])
    calls: list[ToolCall] = field(default_factory=list[ToolCall])
    moved_to: int | None = None

    async def catalogue(self) -> Catalogue:
        return await self.inner.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        if call.name in READS and not self._outside_read(call):
            return await self.inner.call(call)
        if call.name in READS:
            return ToolResult(call.id, json.dumps({"file": "captured, not served"}), outside=True)
        if call.name == RUN:
            self.changes.append(call)
            return ToolResult(call.id, self.capture.run_result)
        if call.name == MOVE:
            self.moved_to = _bench_of(call)
        self.changes.append(call)
        return ToolResult(call.id, json.dumps({"ok": True, "recorded": True}))

    def _outside_read(self, call: ToolCall) -> bool:
        wanted = call.arguments.get("piece_id")
        return call.name == "bench_read_piece" and any(
            p.id == wanted and p.kind in OUTSIDE_KINDS for p in self.capture.pieces)

    def calls_named(self, name: str) -> int:
        return sum(c.name == name for c in self.calls)


def _bench_of(call: ToolCall) -> int | None:
    bench = call.arguments.get("bench_id")
    return bench if isinstance(bench, int) else None


class Clocked(RecordingInference):
    """Every `step` moves `clock` by `step_s` fake seconds; the `fail_at`th step (from 1) raises InferenceUnavailable
    once."""

    def __init__(self, inner: Inference, advance: "Clock", step_s: float, fail_at: int | None) -> None:
        super().__init__(inner)
        self._clock, self._step_s, self._fail_at, self._asked = advance, step_s, fail_at, 0

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self._clock.now += self._step_s
        self._asked += 1
        if self._asked == self._fail_at:
            raise InferenceUnavailable("scripted failure")
        return await super().step(task, prompt, output, conversation_id=conversation_id)


class Clock:
    """Seconds a case moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Recorder(Steps):
    """What a runner would have saved: the entries and round in flight, the work done, and the tool that first tainted it."""

    entries: tuple[Entry, ...] = ()
    rounds: int = 0
    calls: int = 0
    asked_now: ToolCalls | None = None
    done: dict[str, ToolResult] = field(default_factory=dict[str, ToolResult])
    seconds: float = 0.0
    taken: int = 0
    tainted_by: str | None = None

    async def asked(self, entries: tuple[Entry, ...], asked: ToolCalls, rounds: int, calls: int) -> None:
        self.entries, self.asked_now, self.rounds, self.calls, self.done = entries, asked, rounds, calls, {}

    async def ran(self, result: ToolResult) -> None:
        self.done[result.call_id] = result

    async def tainted(self, tool: str) -> bool:
        first = self.tainted_by is None
        self.tainted_by = tool if first else self.tainted_by
        return first

    @property
    def windows(self) -> int:
        return self.taken

    async def windowed(self) -> None:
        self.taken += 1

    async def worked(self, seconds: float) -> None:
        self.seconds = seconds


def names(specs: Sequence[ToolSpec]) -> tuple[str, ...]:
    return tuple(s.name for s in specs)
