"""A reply refused as `Unhanded` (a message arrived for the turn after its last hand) is gone on from by
`answering.stored`: the turn is handed what it missed and steps again. This holds when the refused reply came from the
closing step after the last tool round, which another runner's resume reaches the same way."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

import pytest
from ashley.channels import answering, tool_loop
from ashley.channels.inflight import Work
from ashley.channels.model import Medium
from ashley.channels.landing import Landing
from ashley.channels.limits import Limits
from ashley.channels.tool_loop import Answer, Arrived
from ashley.conversations.conversations import Unhanded
from ashley.conversations.model import Kind
from ashley.inference.model import Entry, Message, SystemPrompt, ToolCall, ToolResult
from ashley.inference.reply import Reply
from ashley.tools.tools import Catalogue
from answer_dropped_blind_support import GOOD, HISTORY, SAID_ONLY, SECOND, SWITCH, SYSTEM, WRITTEN_ONLY, Model, Switch, limits, switch_on


class Fixed(Landing):
    """A landing that never moves: the turn's own kind, limits and tools."""

    def __init__(self, lim: Limits, source: Switch) -> None:
        self._lim = lim
        self._source = source
        self._arrived = None

    @property
    def kind(self) -> Kind:
        return "chat"

    @property
    def limits(self) -> Limits:
        return self._lim

    async def catalogue(self) -> Catalogue:
        return await self._source.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        return await self._source.call(call)

    async def closing(self, reply: Reply) -> Reply:
        return reply


class Handing(Work):
    """A work that hands the turn one message it missed, once."""

    def __init__(self) -> None:
        self.handed: list[tuple[int, int]] = []

    async def steer(self, entries: tuple[Entry, ...], rounds: int, calls: int) -> tuple[Message, ...]:
        self.handed.append((rounds, calls))
        return (Message("person", "and the porch too"),) if len(self.handed) == 1 else ()


async def _no_move(system: Mapping[str, SystemPrompt]) -> Arrived | None:
    return None


def _store_refusing_once() -> tuple[list[Reply], Callable[[Reply], Awaitable[None]]]:
    stored: list[Reply] = []

    async def store(reply: Reply) -> None:
        if not stored:
            stored.append(reply)
            raise Unhanded()
        stored.append(reply)

    return stored, store


@pytest.mark.parametrize("max_rounds", [6, 1])
def test_a_reply_refused_as_unhanded_is_gone_on_from_whatever_round_it_came_in(loop: Model, max_rounds: int) -> None:
    source = Switch()
    lim = limits(max_rounds)
    loop.play(switch_on(), GOOD)
    first = asyncio.run(tool_loop.answer("chat", SYSTEM, HISTORY, (SWITCH,), lim, 7, source=source))
    assert isinstance(first, Answer) and first.reply == GOOD
    if max_rounds == 1:
        assert first.rounds == max_rounds, "the premise: the answer came from the closing step"
    loop.play(SECOND)
    stored, store = _store_refusing_once()
    going = answering.Going(Fixed(lim, source), 7, SYSTEM, (SWITCH,), False, time.perf_counter(), _no_move, "text")
    work = Handing()

    out = asyncio.run(answering.stored(work, first, store, going))

    assert out.reply == SECOND and stored == [GOOD, SECOND]
    assert work.handed
    assert len(source.ran) == 1
    assert loop.choices[-1] == ("none" if max_rounds == 1 else "auto")


@pytest.mark.parametrize(("medium", "wrong", "right"), [("spoken", WRITTEN_ONLY, SAID_ONLY), ("text", SAID_ONLY, WRITTEN_ONLY)])
def test_the_turn_gone_on_from_judges_its_replies_by_its_medium(loop: Model, medium: Medium, wrong: Reply, right: Reply) -> None:
    source = Switch()
    loop.play(GOOD)
    first = asyncio.run(tool_loop.answer("chat", SYSTEM, HISTORY, (SWITCH,), limits(), 7, source=source, medium=medium))
    assert isinstance(first, Answer)
    loop.play(wrong, right)
    stored, store = _store_refusing_once()
    going = answering.Going(Fixed(limits(), source), 7, SYSTEM, (SWITCH,), False, time.perf_counter(), _no_move, medium)

    out = asyncio.run(answering.stored(Handing(), first, store, going))

    assert out.reply == right and stored == [first.reply, right]
