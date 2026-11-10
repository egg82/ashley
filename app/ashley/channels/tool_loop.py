"""The tool loop of one reply (`respond` steps 3 and 5): the catalogue on offer, then model steps and tool calls until
she answers. Every tool is offered from the first step."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from .. import logs, services
from ..conversations.model import Kind
from ..inference.inference import Inference, InferenceRefused, InferenceRejected, InferenceUnavailable
from ..inference.model import (Entry, Message, Prompt, SystemPrompt, Task, ToolCalls, ToolChoice, ToolResult,
                              ToolResults, ToolSpec)
from ..inference.reply import Reply
from ..tools.tools import Catalogue, Tools, ToolsUnavailable
from . import aside, cutoff, ending, hand_off, loop_limits, refused, reshorten, taint, tool_round, unsaid, windows as window
from .escalation import Escalating, Escalation, Trigger
from .limits import Limits
from .model import Medium
from .pace import Pace as _Pace, pace as _pace
from .reshorten import RESHORTENED as RESHORTENED
from .steps import NO_STEPS as NO_STEPS, Steps as Steps

log = logging.getLogger("ashley.tools")
turn_log = logging.getLogger("ashley.channels")


Closed = Literal["answer", "deadline", "stood", "wrapped"]
"""How a turn ended: `answer`, a step under tool choice `auto` (or the closing one at `max_tool_rounds`); `deadline`, the
closing step forced by `deadline_s`; `window`, the same after the turn took at least one fresh window; `stood`, a reply
that was not the answer asked once to say where things stand (`unsaid.STAND`); `wrapped`, a refusal wrapped up."""


@dataclass(frozen=True)
class Answer:
    """Her reply, the rounds of tool calls it took, how many calls those rounds made, how many steps were asked
    again with the act note (`unsaid.acting`) because a reply said it was not the answer, and the entries the reply followed.
    `changes`: how many of those calls were to a tool whose spec does not read. `closed`: how the turn ended."""

    reply: Reply
    rounds: int
    calls: int
    required: int = 0
    entries: tuple[Entry, ...] = field(default=(), compare=False)
    changes: int = 0
    closed: Closed = "answer"

    def closing(self) -> dict[str, object]:
        """What `respond.done` logs of how the turn ended: `changes`, `closed` and the reply's `answers`."""
        return {"changes": self.changes, "closed": self.closed, "answers": self.reply.answers}


HeldBy = Literal["not_answer", "aside_budget", "escalate"]
"""Why a turn held: `not_answer`, a reply said it was not the answer; `aside_budget`, the turn ran past its kind's
`hold_after_s` with no answer and her latest aside went out; `escalate`, the turn is to go on on the stronger route
(`channels.escalation`) and the line is what she says meanwhile."""


@dataclass(frozen=True)
class Stepping:
    """A model step still running when the turn held: its `choice` of tool use, and whether it was the deadline's
    closing step (`late`)."""

    future: asyncio.Future[Reply | ToolCalls]
    choice: ToolChoice
    late: bool


@dataclass(frozen=True)
class Held:
    """A reply that is not the answer ("let me check"), to deliver now, and where the loop stopped, to `resume` from:
    the entries so far, the round it came in, the calls made before it, and why it held. `running`, when set, is the
    results of the round whose `ToolCalls` end `entries`, still being run; `resume` awaits it. `stepping`, when set, is
    the model step asked of `entries` that is still running, which `resume` takes as that round's step. `trigger`:
    what escalated the turn, when `by` is `escalate`."""

    reply: Reply
    entries: tuple[Entry, ...]
    rounds: int
    calls: int
    by: HeldBy = "not_answer"
    running: asyncio.Future[ToolResults] | None = None
    trigger: Trigger | None = None
    stepping: Stepping | None = None


@dataclass(frozen=True)
class Arrived:
    """What a turn is offered from its next step on, once its page has moved to a bench: those `tools`, this
    `system` and, when given, these `limits` and conversation `kind` in place of the turn's (a bench's talk has room to
    work, and its own model)."""

    tools: tuple[ToolSpec, ...]
    system: Mapping[str, SystemPrompt]
    limits: Limits | None = None
    kind: Kind | None = None


Arrive = Callable[[Mapping[str, SystemPrompt]], Awaitable[Arrived | None]]
"""Asked after each round of tool calls with the system prompt then in force; an `Arrived` when the turn's page moved."""


@dataclass(frozen=True)
class Progress:
    """How far a turn's loop got: the entries before the round in flight, the next round to step (that round's
    number when one is in flight), the calls asked so far, and the round in flight with the results it has (`done`,
    by call id), when there is one. `steered`: the ids of the person turns handed to the turn so far
    (`channels.steering`)."""

    entries: tuple[Entry, ...]
    rounds: int
    calls: int
    asked: ToolCalls | None = None
    done: Mapping[str, ToolResult] = field(default_factory=dict[str, ToolResult])
    steered: tuple[int, ...] = ()


async def offered(source: Tools) -> Catalogue | None:
    """What `source` offers now; None when it cannot be reached, and the reply goes on without tools."""
    try:
        return await source.catalogue()
    except ToolsUnavailable:
        return None


async def answer(kind: Task, system: Mapping[str, SystemPrompt], history: tuple[Message, ...], tools: tuple[ToolSpec, ...],
                 limits: Limits, conversation_id: int | None = None, hold: bool = False,
                 source: Tools | None = None, started: float | None = None,
                 clock: Callable[[], float] = time.perf_counter, steps: Steps = NO_STEPS,
                 arrive: Arrive | None = None, medium: Medium = "text",
                 escalation: Escalation | None = None) -> Answer | Held:
    """Step the model with tool choice `auto` and run each round of `ToolCalls` it asks for, at most
    `limits.max_tool_rounds` rounds, then step once more with tool choice `none`. Every one of `tools` is offered on
    every step. A reply under `auto` whose `answers` is false, while tools are offered, is not the answer: with `hold`,
    the first such reply is returned as `Held`, for the caller to deliver and `resume`; otherwise it is dropped and the
    step asked again once under `auto` with the act note (`unsaid.acting`). Each call is run by `source`, the locator's `Tools` when None.
    A read identical in name and arguments to one already made in the reply is not run again (its result points at the
    earlier call, logged `tools.repeat`), unless a change (a call to a tool whose spec in `tools` does not read; a
    name not in `tools` counts as one) has run since; a change is never deduped.
    Every step is recorded against `conversation_id`. A turn whose every route rejected the request (`InferenceRejected`)
    ends with `unsaid.rejected()` as its answer, logged `respond.ended` reason `inference_rejected`, and is not retried.
    Raises InferenceUnavailable, InferenceRefused.
    Time is `clock` seconds since `started` (the call itself when None), read before each step. With `hold` and
    tools offered, every tool is offered with `aside.FIELD` added (`aside.offered`) and the call reaches `source`
    without it; before a step, once `limits.hold_after_s` has passed and some call carried an aside, the latest is
    returned as `Held` by `aside_budget` (`aside.holding`), and so is a round's own aside when the budget passes while
    its calls run: the calls run on, one at a time, and the `Held` carries them as `running`. The same when the budget
    passes while a step runs: the `Held` carries it as `stepping`, uncancelled. Once `limits.deadline_s`
    has passed, the next step is the closing one, under tool choice `none`, logged `respond.deadline` with the
    conversation, the rounds made and duration_ms. Before that, a turn that has made calls takes a fresh window
    (`Limits.windows`, counted by `steps.windows`): its pace starts again, `steps.windowed` records it, logged
    `respond.window` with the conversation, the windows taken, the rounds made and duration_ms. A closing reply whose
    `answers` is false is never the answer: it takes a window when one is left, else it is asked once more with
    `unsaid.STAND` and that reply is the answer (`respond.stood`). Progress is recorded through `steps`. After each round, `arrive`
    (when given) says whether the turn's page moved to a bench; if so, the next steps are offered its `tools`, with
    `aside` added as the others', and its `system`.

    With an `escalation` (`channels.escalation`), a turn that reaches `max_tool_rounds` or `deadline_s` with no answer,
    or whose reply sets `Reply.escalate`, goes on once on the stronger route from its entries in place of closing here
    (`respond.escalated`). With `hold` it is returned as `Held` by `escalate` first, its line her latest aside or the
    reply's `escalate`; at its limit with `hold` and no aside it closes as before."""
    pace = _pace(limits, started, clock, medium)
    if hold and tools:
        return await _turn(kind, system, list(history), aside.offered(tools), pace, conversation_id, True,
                           aside.Stripped(_or_located(source), tools), steps=steps, arrive=arrive,
                           escalation=escalation)
    return await _turn(kind, system, list(history), tools, pace, conversation_id, hold, _or_located(source),
                       steps=steps, arrive=arrive, escalation=escalation)


async def resume(held: Held, kind: Kind, system: Mapping[str, SystemPrompt], tools: tuple[ToolSpec, ...], limits: Limits,
                 conversation_id: int | None = None, source: Tools | None = None, started: float | None = None,
                 clock: Callable[[], float] = time.perf_counter, steps: Steps = NO_STEPS,
                 arrive: Arrive | None = None, medium: Medium = "text",
                 escalation: Escalation | None = None) -> Answer:
    """The answer `held` stood in for, never held again: a step held `not_answer` is asked again with the act note
    (`unsaid.acting`), one held by `aside_budget` goes on under `auto`, one held by `escalate` goes on on the stronger route
    (`escalation`), once; then the loop as `answer` goes on from that round, a
    later reply that is not the answer asked again the same way.
    `tools` are offered as `answer` offered them with `hold`, and `limits.deadline_s` still counts from `started`.
    Raises InferenceUnavailable, InferenceRefused."""
    entries = [*held.entries, await held.running] if held.running is not None else list(held.entries)
    got = await _turn(kind, system, entries, aside.offered(tools), _pace(limits, started, clock, medium, True),
                      conversation_id, False, aside.Stripped(_or_located(source), tools), held.rounds,
                      held.by == "not_answer", held.calls, steps, arrive, escalation, held.trigger, held.stepping)
    assert isinstance(got, Answer)
    return got


async def resumed(progress: Progress, kind: Kind, system: Mapping[str, SystemPrompt], tools: tuple[ToolSpec, ...],
                  limits: Limits, conversation_id: int, source: Tools, asides: bool, started: float,
                  clock: Callable[[], float] = time.perf_counter, steps: Steps = NO_STEPS,
                  arrive: Arrive | None = None, medium: Medium = "text",
                  escalation: Escalation | None = None) -> Answer:
    """The answer of a turn another runner began, from `progress`, never held: the round in flight finishes first,
    each call in `done` taken as its result and every other call run as `answer` runs one; then the loop goes on
    under `auto`. With `asides`, `tools` are offered as `answer` offered them with `hold`. Raises InferenceUnavailable,
    InferenceRefused."""
    offered = aside.offered(tools) if asides else tools
    running = aside.Stripped(source, tools) if asides else source
    entries = list(progress.entries)
    start = progress.rounds
    if progress.asked is not None:
        reading = {t.name for t in offered if t.reads}
        results = await tool_round.run(progress.asked, limits.max_tool_result_chars, running, reading,
                                       tool_round.reads_made(entries, reading), conversation_id,
                                       taint.specs_outside(offered), steps, dict(progress.done))
        entries += [progress.asked, results]
        start += 1
    got = await _turn(kind, system, entries, offered, _pace(limits, started, clock, medium, True), conversation_id, False,
                      running, start, False, progress.calls, steps, arrive, escalation)
    assert isinstance(got, Answer)
    return got


async def _turn(kind: Task, system: Mapping[str, SystemPrompt], entries: list[Entry], tools: tuple[ToolSpec, ...],
                pace: _Pace, conversation_id: int | None, hold: bool, source: Tools, start: int = 0,
                required_first: bool = False, calls: int = 0, steps: Steps = NO_STEPS,
                arrive: Arrive | None = None, escalation: Escalation | None = None,
                escalated: Trigger | None = None, stepping: Stepping | None = None) -> Answer | Held:
    """`_loop` and the turn's one escalation (`channels.escalation`): on the stronger route from the start when it has
    already (`escalated`, or `steps` says so); else when the loop stops to escalate, logged `respond.escalated`, held
    with the line when it may hold and otherwise gone on at once from the same round."""
    trigger = escalated or steps.escalated
    if escalation is not None and trigger is not None:
        kind, pace, escalation = escalation.task, replace(pace, limits=escalation.limits), None
    try:
        got = await _loop(kind, system, entries, tools, pace, conversation_id, hold, source, start, required_first,
                          calls, steps, arrive, escalation, stepping)
    except InferenceRefused:
        if not pace.wraps:
            raise
        return Answer(await refused.wrapped(_step, system, tools, entries, pace.medium, conversation_id), start, calls,
                      entries=tuple(entries), changes=tool_round.changes_in(entries, {t.name for t in tools if t.reads}),
                      closed="wrapped")
    except InferenceRejected:
        ending.record("inference_rejected", conversation_id, "told")
        return Answer(unsaid.rejected(), start, calls)
    if not isinstance(got, Escalating):
        return got
    assert escalation is not None
    logs.info(turn_log, "respond.escalated", conversation=conversation_id, trigger=got.trigger, rounds=got.rounds,
              from_route=kind, to_route=escalation.task, duration_ms=pace.ms())
    await steps.escalate(got.trigger)
    if got.line is not None:
        return Held(aside.holding(got.line), got.entries, got.rounds, got.calls, "escalate", None, got.trigger)
    return await _turn(kind, system, list(got.entries), tools, pace, conversation_id, False, source, got.rounds, False,
                       got.calls, steps, arrive, escalation, got.trigger)


async def _loop(kind: Task, system: Mapping[str, SystemPrompt], entries: list[Entry], tools: tuple[ToolSpec, ...],
                pace: _Pace, conversation_id: int | None, hold: bool, source: Tools, start: int = 0,
                required_first: bool = False, calls: int = 0, steps: Steps = NO_STEPS,
                arrive: Arrive | None = None, escalation: Escalation | None = None,
                stepping: Stepping | None = None) -> Answer | Held | Escalating:
    """From round `start`, its step asked with the act note (`unsaid.acting`) when `required_first`. Stops with `Escalating`
    when `escalation` is given and the turn reaches its limit with no answer (`_limit_stop`) or its reply sets
    `Reply.escalate`; a turn whose page moved to a bench no longer escalates."""
    required, shortened, nothing = 0, 0, 0
    reading = {t.name for t in tools if t.reads}
    pace.windows = steps.windows
    rounds = start - 1
    pending = stepping
    while True:
        rounds += 1
        moved = await _arrived(arrive, system)
        if pending is None:
            entries += await steps.steer(tuple(entries), rounds, calls)
        if moved is not None:
            system, escalation = moved.system, None
            pace, kind, tools, source = _moved_to(moved, hold, pace, kind, source)
            reading |= {t.name for t in tools if t.reads}
        if rounds > pace.limits.max_tool_rounds:
            break
        line = aside.latest(entries) if hold and pace.past(pace.limits.hold_after_s) else None
        if line is not None:
            return Held(aside.holding(line), tuple(entries), rounds, calls, "aside_budget")
        await window.taken(pace, steps, rounds, calls, conversation_id)
        stop = loop_limits.limit_stop(escalation, hold, pace, rounds, calls, entries)
        if stop is not None:
            return stop
        late = loop_limits.late(pace, rounds, conversation_id)
        choice: ToolChoice = "auto" if rounds < pace.limits.max_tool_rounds and not late else "none"
        if pending is not None:
            step, choice, late = pending.future, pending.choice, pending.late
            pending = None
        else:
            acting = rounds == start and required_first and not late
            prompt = hand_off.step_prompt(system, entries, tools, (choice, calls, acting), (pace, rounds, steps.cut_off))
            step = asyncio.ensure_future(cutoff.asked(_step, steps, rounds, kind, prompt, conversation_id))
            required += acting
            held = await _held_mid_step(step, entries, rounds, calls, (hold, pace, choice, late))
            if held is not None:
                return held
        got = await step
        if escalation is not None and isinstance(got, Reply) and got.escalate:
            return Escalating("b", tuple(entries), rounds, calls, got.escalate if hold else None)
        if isinstance(got, Reply) and not got.answers and choice == "auto" and tools:
            if hold:
                return Held(got, tuple(entries), rounds, calls)
            required += 1
            got = await cutoff.asked(_step, steps, rounds, kind, Prompt(system, unsaid.acting(entries), tools, "auto"),
                                     conversation_id)
        stood = isinstance(got, Reply) and not got.answers and choice == "none"
        if isinstance(got, Reply) and stood:
            if await window.taken(pace, steps, rounds, calls, conversation_id, True):
                rounds -= 1
                continue
            got = await unsaid.stood(_step, got, kind, system, tools, entries, calls, rounds, conversation_id)
        got, again, shortened = await reshorten.shorter(_step, got, choice, kind, system, tools, entries, pace.limits,
                                                        shortened, conversation_id)
        if again:
            continue
        if isinstance(got, Reply) and unsaid.empty(got, pace.medium):
            nothing += 1
            got = await unsaid.asked_again(_step, kind, system, tools, entries, nothing, pace.medium, conversation_id)
        if isinstance(got, Reply):
            back = await _handed(steps, entries, got, rounds, calls, choice)
            if back is None:
                return Answer(got, rounds, calls, required, tuple(entries), tool_round.changes_in(entries, reading),
                              _closed(stood, late))
            rounds = back
            continue
        if choice == "none":
            break
        calls += len(got.calls)
        held = await _round(got, entries, rounds, calls, (reading, tools, source), (hold, pace, steps), conversation_id)
        if held is not None:
            return held
    raise InferenceUnavailable("the model asked for tools under tool choice none")


async def _held_mid_step(step: asyncio.Future[Reply | ToolCalls], entries: list[Entry], rounds: int, calls: int,
                         timing: tuple[bool, _Pace, ToolChoice, bool]) -> Held | None:
    """`Held` by `aside_budget`, carrying the still-running `step`, when it outlasts `hold_after_s` and an aside exists."""
    hold, pace, choice, late = timing
    line = aside.latest(entries) if hold else None
    if line is None or await loop_limits.ends_within(step, pace.left(pace.limits.hold_after_s)):
        return None
    return Held(aside.holding(line), tuple(entries), rounds, calls, "aside_budget", stepping=Stepping(step, choice, late))


async def _handed(steps: Steps, entries: list[Entry], reply: Reply, rounds: int, calls: int, choice: ToolChoice) -> int | None:
    """None when nothing was said to the turn since it last asked; else its draft `reply` and what was said are added to
    `entries` and the round to go on from is returned."""
    draft = (*entries, Message("ashley", reply.text))
    ahead = rounds if choice == "none" else rounds + 1
    said = await steps.steer(draft, ahead, calls)
    if not said:
        return None
    entries += [draft[-1], *said]
    return ahead - 1


def _closed(stood: bool, late: bool) -> Closed:
    return "stood" if stood else "answer" if not late else "deadline"


async def _arrived(arrive: Arrive | None, system: Mapping[str, SystemPrompt]) -> Arrived | None:
    return None if arrive is None else await arrive(system)


def _moved_to(moved: Arrived, hold: bool, pace: _Pace, kind: Task,
              source: Tools) -> tuple[_Pace, Task, tuple[ToolSpec, ...], Tools]:
    """The pace, route, tools (with asides when `hold`) and tool source of a turn whose page moved to a bench."""
    pace = pace if moved.limits is None else replace(pace, limits=moved.limits)
    tools = aside.offered(moved.tools) if hold else moved.tools
    return (pace, kind if moved.kind is None else moved.kind, tools,
            source.offering(moved.tools) if isinstance(source, aside.Stripped) else source)


async def _round(asked: ToolCalls, entries: list[Entry], rounds: int, calls: int,
                 using: tuple[set[str], tuple[ToolSpec, ...], Tools], timing: tuple[bool, _Pace, Steps],
                 conversation_id: int | None) -> Held | None:
    """One round of `asked` run and its results added to `entries`, the work done recorded; `Held` by `aside_budget` when
    the budget passes while its calls run, which carries them as `running`."""
    (reading, tools, source), (hold, pace, steps) = using, timing
    made = tool_round.reads_made(entries, reading)
    await steps.asked(tuple(entries), asked, rounds, calls)
    running = asyncio.ensure_future(tool_round.run(asked, pace.limits.max_tool_result_chars, source, reading, made,
                                                   conversation_id, taint.specs_outside(tools), steps))
    line = aside.latest((*entries, asked)) if hold else None
    if line is not None and not await loop_limits.ends_within(running, pace.left(pace.limits.hold_after_s)):
        return Held(aside.holding(line), (*entries, asked), rounds + 1, calls, "aside_budget", running)
    entries += [asked, await running]
    await steps.worked(pace.ms() / 1000)
    return None


async def _step(kind: Task, prompt: Prompt, conversation_id: int | None) -> Reply | ToolCalls:
    return await services.get(Inference).step(kind, prompt, Reply, conversation_id=conversation_id)


def _or_located(source: Tools | None) -> Tools:
    return source if source is not None else services.get(Tools)
