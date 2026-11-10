"""Pieces of the `Outside` tests: an in-memory Proposals that keeps a person-scoped topic once per person, tools that
record what ran, and a builder for the decorator in front of them."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any

from ashley import services
from ashley.inference.model import Tier, ToolCall, ToolResult, ToolSpec
from ashley.db.pool import PoolDatabase
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import Payload, Topic, encode
from ashley.senses.proposals import Proposal, ProposalRefused, Proposals, refusal
from ashley.tools.outside import Outside, Standing
from ashley.tools.outside_config import OutsideConfig, load
from ashley.tools.tools import Catalogue, Tools
from datetime import UTC, datetime

from contract.conversations_support import household, person

SPEAKER, HOUSEHOLD, CONVERSATION, TURN = 7, 1, 40, 100


def run(scenario: Coroutine[Any, Any, None]) -> None:
    asyncio.run(asyncio.wait_for(scenario, 10))


class Memory(Proposals):
    """Proposals in a dict, keyed as the Postgres store keys them: by person and topic when the topic is person-scoped."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, str, int | None], Proposal[Any]] = {}
        self.proposed = 0

    def _key(self, made_by: int, conversation_id: int, topic: Topic[Any]) -> tuple[int, str, int | None]:
        return made_by, topic.name, None if topic.scope == "person" else conversation_id

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        name, _ = encode(proposal.payload)
        scope = None if name == "outside" else proposal.conversation_id
        self.rows[(proposal.made_by, name, scope)] = replace(proposal, id=self.proposed + 1)
        self.proposed += 1
        return self.proposed

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        return self.rows.get(self._key(made_by, conversation_id, topic))

    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        found = self.rows.get(self._key(made_by, conversation_id, topic))
        if found is None:
            raise ProposalRefused("none")
        why = refusal(found, turn_id, datetime.now(UTC), ttl_s)
        if why is not None:
            raise ProposalRefused(why)
        del self.rows[self._key(made_by, conversation_id, topic)]
        return found

    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        raise AssertionError("not used")

    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        raise AssertionError("not used")


def spec(name: str, reads: bool = False, outside: bool = False, agrees: bool = False, tier: Tier = "judged") -> ToolSpec:
    return ToolSpec(name, name, {"type": "object"}, reads=reads, outside=outside, agrees=agrees, tier=tier)


@dataclass
class Fake(Tools):
    """Offers `specs`, records each call in `ran`, answers from `results` by name (else `ok`)."""

    specs: tuple[ToolSpec, ...]
    results: dict[str, ToolResult] = field(default_factory=dict[str, ToolResult])
    ran: list[ToolCall] = field(default_factory=list[ToolCall])

    async def catalogue(self) -> Catalogue:
        return Catalogue(self.specs, None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call)
        return replace(self.results.get(call.name, ToolResult(call.id, "ok")), call_id=call.id)


class Tainted:
    """Records `tainted` calls; may raise."""

    def __init__(self, raises: bool = False) -> None:
        self.seen: list[str] = []
        self.raises = raises
        self.ran_before: list[int] = []

    async def tainted(self, tool: str) -> bool:
        if self.raises:
            raise RuntimeError("the turn was lost")
        self.seen.append(tool)
        return len(self.seen) == 1


STANDING = Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=True)
TOOLS = (spec("look", reads=True, outside=True), spec("peek", reads=True), spec("lamp"), spec("garage"),
         spec("confirm", agrees=True))


WORDS = ("turn it on",)


async def said() -> Sequence[str]:
    """What the person said, as the turn's `words` reads it."""
    return WORDS


def build(fake: Fake | None = None, standing: Standing | None = STANDING, turn: int = TURN, tainted: str | None = None,
          steps: Tainted | None = None, config: OutsideConfig | None = None) -> tuple[Outside, Fake, Memory]:
    memory = Memory()
    services.register(Proposals, memory)
    inner = fake or Fake(TOOLS)
    return Outside(inner, standing, (CONVERSATION, turn), steps, tainted, config, said), inner, memory


def asked(name: str, call_id: str = "c1", **arguments: object) -> ToolCall:
    return ToolCall(call_id, name, arguments)


def small(**changes: float) -> OutsideConfig:
    return replace(load(), **changes)


@dataclass
class Store:
    """The Postgres proposals store on a migrated database with a household of Alana and Sam."""

    store: Proposals
    house: int
    alana: int
    sam: int


@asynccontextmanager
async def store(url: str) -> AsyncGenerator[Store]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    house = household(url, "oa")
    kept = PostgresProposals(db)
    services.register(Proposals, kept)
    try:
        yield Store(kept, house, person(url, house, "Alana"), person(url, house, "Sam"))
    finally:
        services.unregister(Proposals)
        await db.close()
