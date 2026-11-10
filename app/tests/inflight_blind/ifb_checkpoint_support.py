"""Builders for checkpoints: plain constructors for the examples, Hypothesis strategies for the property."""

from typing import Any, get_args

from ashley.channels.checkpoint import Checkpoint
from ashley.channels.model import Audience, Inbound, Medium
from ashley.channels.tool_loop import Progress
from ashley.conversations.model import Channel, Kind
from ashley.inference.model import Entry, Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults
from hypothesis import strategies as st


def inbound(text: str = "turn on the lamp") -> Inbound:
    return Inbound(household_id=10, thread="web:1", text=text, kind="chat", medium="text", audience="owner",
                   speaker_id=1, shared=False, place=None, channel="web", later=True, later_by="turn",
                   opens_benches=True, on_page=True)


def checkpoint(progress: Progress | None = None, started: frozenset[str] = frozenset(),
               offered: frozenset[int] = frozenset(), phone: int | None = None) -> Checkpoint:
    start = Progress((Message("person", "turn on the lamp"),), 0, 0) if progress is None else progress
    return Checkpoint(inbound(), 5, 77, 1, {"default": SystemPrompt("system", "now")}, start, started, offered, phone)


def asked(*calls: tuple[str, str]) -> Progress:
    """A turn partway through a round that asked for `calls` ((id, tool name)), none with a result."""
    return Progress((Message("person", "turn on the lamp"),), 0, len(calls),
                    ToolCalls(tuple(ToolCall(i, name, {"what": "lamp"}) for i, name in calls)))


# --- strategies ------------------------------------------------------------------------------------------------

words = st.text(min_size=1).filter(lambda s: s.strip() != "")
ids = st.integers(min_value=0, max_value=2**62)
json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-2**53, 2**53) | st.floats(allow_nan=False, allow_infinity=False) | st.text(),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(), inner, max_size=3), max_leaves=8)
json_objects = st.dictionaries(st.text(), json_values, max_size=3)


@st.composite
def inbounds(draw: st.DrawFn) -> Inbound:
    return Inbound(
        household_id=draw(ids), thread=draw(words), text=draw(words), kind=draw(st.sampled_from(get_args(Kind))),
        medium=draw(st.sampled_from(get_args(Medium))), audience=draw(st.sampled_from(get_args(Audience))),
        speaker_id=draw(st.none() | ids), shared=draw(st.booleans()), place=draw(st.none() | st.text()),
        channel=draw(st.sampled_from(get_args(Channel))), remembers=draw(st.booleans()),
        heard_as=draw(st.none() | ids), later=draw(st.booleans()), later_by=draw(st.sampled_from(["outbox", "turn"])),
        device_id=draw(st.none() | ids), bench_id=draw(st.none() | ids), opens_benches=draw(st.booleans()),
        on_page=draw(st.booleans()))


@st.composite
def tool_calls(draw: st.DrawFn) -> ToolCalls:
    call_ids = draw(st.lists(words, min_size=1, max_size=3, unique=True))
    return ToolCalls(tuple(ToolCall(i, draw(words), draw(json_objects), draw(json_objects)) for i in call_ids))


@st.composite
def results(draw: st.DrawFn, call_ids: list[str] | None = None) -> tuple[ToolResult, ...]:
    chosen = draw(st.lists(words, max_size=3, unique=True)) if call_ids is None else call_ids
    return tuple(ToolResult(i, draw(st.text()), draw(st.booleans())) for i in chosen)


@st.composite
def entries(draw: st.DrawFn) -> Entry:
    kind = draw(st.sampled_from(["message", "calls", "results"]))
    if kind == "message":
        return Message(draw(st.sampled_from(["person", "ashley"])), draw(words))
    if kind == "calls":
        return draw(tool_calls())
    return ToolResults(draw(results()))


@st.composite
def progresses(draw: st.DrawFn) -> Progress:
    ask = draw(st.none() | tool_calls())
    done: dict[str, ToolResult] = {}
    if ask is not None:
        done = {r.call_id: r for r in draw(results([c.id for c in ask.calls if draw(st.booleans())]))}
    return Progress(tuple(draw(st.lists(entries(), max_size=4))), draw(st.integers(0, 50)), draw(st.integers(0, 500)),
                    ask, done)


@st.composite
def checkpoints(draw: st.DrawFn) -> Checkpoint:
    progress = draw(progresses())
    flying = [c.id for c in progress.asked.calls] if progress.asked else []
    system: dict[str, Any] = {"default": draw(st.builds(_prompt, words, st.text()))}
    system.update(draw(st.dictionaries(words, st.builds(_prompt, words, st.text()), max_size=2)))
    return Checkpoint(draw(inbounds()), draw(ids), draw(ids), draw(st.none() | ids), system, progress,
                      frozenset(draw(st.lists(st.sampled_from(flying), max_size=3))) if flying else frozenset(),
                      frozenset(draw(st.lists(ids, max_size=4))), draw(st.none() | ids), draw(st.none() | words))


def _prompt(stable: str, moment: str) -> SystemPrompt:
    return SystemPrompt(stable, moment)
