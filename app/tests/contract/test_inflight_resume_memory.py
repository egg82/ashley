"""A memory act after the reply is part of the turn's checkpointed work (`decisions.md`, "Work in flight survives its
pod"): once her turn is stored the work stays, holding the act, until the act is carried out. A runner that stops
before it began is resumed and the act carried out once; one that stops while carrying it out is not repeated.

Postgres is real (Conversations and `InFlight`); the model, Memory and the people are fakes, as in
`test_inflight_resume.py`."""

import asyncio
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from ashley import services
from ashley.channels.respond import respond
from ashley.conversations.inflight import Claim, InFlight
from ashley.conversations.model import Conversation, Kind, NewTurn, Turn
from ashley.inference.reply import MemoryAct, Reply
from ashley.memory.memory import Memory
from ashley.memory.model import Asker, Fact, Held, Op, Recalled, Source, Unwritten
from contract.conversations_support import run, scalar
from contract.conversations_support import db_url as db_url
from contract.conversations_support import migrated_template as migrated_template
from contract.profile_support import stored_fact
from contract.test_inflight_resume import CLAIM_S, World, database, sweep
from contract.inflight_outage_support import Outage
from contract.test_inflight_resume import system as system
from contract.test_inflight_resume import world as world

FACT = 7
FORGET = Reply(spoken="Forgotten.", text="Forgotten.", memory=MemoryAct(action="forget", facts=(FACT,)))


@dataclass
class OneFact(Memory):
    """Holds fact 7 for everyone; `forgot` is each forget that reached it; with `hang`, a forget waits forever once
    recorded."""

    household_id: int
    forgot: list[int] = field(default_factory=list[int])
    hang: bool = False
    reached: asyncio.Event = field(default_factory=asyncio.Event)
    tasks: list[asyncio.Task[Any] | None] = field(default_factory=list[asyncio.Task[Any] | None])

    def _fact(self) -> Fact:
        return stored_fact(FACT, "likes tea", standing=True, household_id=self.household_id)

    async def profile(self, asker: Asker) -> tuple[Recalled, ...]:
        return (Recalled(self._fact(), True),)

    async def recall(self, asker: Asker, query: str) -> tuple[Recalled, ...]:
        return ()

    async def held(self, household_id: int, person_id: int, fact_id: int | None = None) -> tuple[Held, ...]:
        return (Held(self._fact(), None, Source(1, "chat", datetime(2026, 1, 1, tzinfo=UTC), True)),)

    async def forget(self, household_id: int, fact_id: int, by: int) -> int:
        self.forgot.append(fact_id)
        self.tasks.append(asyncio.current_task())
        self.reached.set()
        if self.hang:
            await asyncio.Event().wait()
        return 1

    async def similar(self, conversation: Conversation, limit: int) -> tuple[Fact, ...]:
        raise AssertionError("not used")

    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        raise AssertionError("not used")

    async def embed_missing(self, limit: int) -> int:
        raise AssertionError("not used")

    async def unwritten(self, idle_after_s: Mapping[Kind, float], limit: int,
                        max_failures: int) -> tuple[Unwritten, ...]:
        raise AssertionError("not used")

    async def write_failed(self, household_id: int, conversation_id: int, through: int) -> int:
        raise AssertionError("not used")

    async def written_through(self, conversation_id: int) -> int | None:
        raise AssertionError("not used")


@pytest.fixture
def memory(world: World) -> Generator[OneFact]:
    made = OneFact(world.who.household_id)
    services.register(Memory, made)
    yield made
    services.unregister(Memory)


@dataclass
class DownAfterFinish(Outage):
    """The real store, which becomes unreachable once her turn is stored: the runner cannot record the act begun."""

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        stored = await self.real.finish(claim, turn, after)
        self.down = True
        return stored


def work_rows(world: World) -> int:
    return int(scalar(world.url, "SELECT count(*) FROM turn_work"))


async def settled() -> None:
    for _ in range(20):
        await asyncio.sleep(0.01)


def test_a_forget_whose_runner_stopped_before_it_began_is_carried_out_once_by_the_resumer(
        world: World, memory: OneFact) -> None:
    world.first.inference.script = [FORGET]

    async def go() -> None:
        async with database(world):
            outage = DownAfterFinish(services.get(InFlight))
            services.register(InFlight, outage)
            world.as_pod(world.first)
            out = await respond(world.inbound())
            assert out.body == FORGET.text
            await settled()
            assert memory.forgot == [], "nothing was carried out that was not recorded begun"
            outage.down = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1
            await settled()
            assert await sweep() == 0

    run(go())
    assert memory.forgot == [FACT]
    assert world.hers() == [FORGET.text]
    assert work_rows(world) == 0
    assert world.second.inference.prompts == [], "the answer is not asked for again"


def test_a_forget_cut_off_while_it_ran_is_not_carried_out_again(world: World, memory: OneFact) -> None:
    world.first.inference.script = [FORGET]
    memory.hang = True

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound())
            await asyncio.wait_for(memory.reached.wait(), 5)
            (running,) = memory.tasks
            assert running is not None
            running.cancel()
            await settled()
            memory.hang = False
            await asyncio.sleep(CLAIM_S * 1.5)
            world.as_pod(world.second)
            assert await sweep() == 1
            await settled()

    run(go())
    assert memory.forgot == [FACT]
    assert world.hers() == [FORGET.text]
    assert work_rows(world) == 0


def test_a_forget_carried_out_leaves_no_work(world: World, memory: OneFact) -> None:
    world.first.inference.script = [FORGET]

    async def go() -> None:
        async with database(world):
            world.as_pod(world.first)
            await respond(world.inbound())
            await settled()
            await asyncio.sleep(CLAIM_S * 1.5)
            assert await sweep() == 0

    run(go())
    assert memory.forgot == [FACT]
    assert work_rows(world) == 0
