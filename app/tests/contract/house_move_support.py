"""Support for the blind contract tests of `house_state` and `move_page`: a recording Workshop that lists open benches,
a wired `move_page`, and the logfmt reader."""

import asyncio
import json
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.events import PageMoved
from ashley.tools.move_page import MovePageTools
from ashley.workshop.model import Bench, Owner
from ashley.workshop.reactions import Unseen
from ashley.workshop.workshop import Placed, Workshop, WorkshopUnavailable
from ashley.live.live import Live as Live_
from live_support import FakeLive

HOUSEHOLD = 4
PERSON = 9
OTHER_PERSON = 10
OPEN = 31
CLOSED = 32
OTHERS = 33


@dataclass
class Benches(Workshop):
    """`open_benches` answers the open benches of the owner asked about only: bench ids per person id."""

    open_of: dict[int, tuple[int, ...]] = field(default_factory=dict[int, tuple[int, ...]])
    down: bool = False
    asked: list[Owner] = field(default_factory=list[Owner])

    async def of_kind(self, household_id: int, kind: str) -> tuple[Placed, ...]:
        raise NotImplementedError

    async def open_benches(self, owner: Owner) -> list[Bench]:
        self.asked.append(owner)
        if self.down:
            raise WorkshopUnavailable("down")
        at = datetime(2026, 10, 29, tzinfo=UTC)
        return [Bench(i, owner.household_id, owner.person_id, "B", at, None) for i in self.open_of.get(owner.person_id, ())]

    async def open(self, owner: Owner, title: str) -> Bench:
        raise NotImplementedError

    async def close(self, owner: Owner, bench_id: int) -> Bench:
        raise NotImplementedError

    async def closed_benches(self, owner: Owner) -> list[Bench]:
        raise NotImplementedError

    async def reopen(self, owner: Owner, bench_id: int) -> Bench:
        raise NotImplementedError

    async def read(self, owner: Owner, bench_id: int) -> Any:
        raise NotImplementedError

    async def apply(self, owner: Owner, bench_id: int, command: Any) -> Any:
        raise NotImplementedError

    async def undo_turn(self, owner: Owner, bench_id: int, by: Any, seq: int) -> Any:
        raise NotImplementedError

    async def log(self, owner: Owner, bench_id: int) -> Any:
        raise NotImplementedError

    async def unseen(self, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
        raise NotImplementedError

    async def reaction_ages(self, bench_id: int, window_s: float) -> tuple[float, ...]:
        raise NotImplementedError

    async def reacted(self, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
        raise NotImplementedError


@dataclass
class Page:
    tools: MovePageTools
    live: FakeLive
    workshop: Benches

    def move(self, **arguments: object) -> ToolResult:
        return asyncio.run(self.tools.call(ToolCall("m1", "move_page", arguments)))

    def moved(self) -> list[PageMoved]:
        return [e for e in self.live.published if isinstance(e, PageMoved)]


@pytest.fixture
def page() -> Generator[Page]:
    """The speaker (PERSON of HOUSEHOLD) owns benches OPEN; OTHER_PERSON owns OTHERS. A Live and a Workshop are wired."""
    live = FakeLive()
    workshop = Benches({PERSON: (OPEN,), OTHER_PERSON: (OTHERS,)})
    services.register(Live_, live)
    services.register(Workshop, workshop)
    yield Page(MovePageTools(HOUSEHOLD, PERSON), live, workshop)
    services.unregister(Live_)
    services.unregister(Workshop)


def body(result: ToolResult) -> Any:
    return json.loads(result.content)
