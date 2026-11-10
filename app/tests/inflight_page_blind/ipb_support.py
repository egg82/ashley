"""Support for the inflight-page blind tests: Conversations, InFlight and the Outbox on one migrated database."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ashley import services
from ashley.channels.model import Outbound
from ashley.channels.outbox import Outbox, Pushed
from ashley.channels.postgres_outbox import PostgresOutbox
from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, InFlight
from ashley.conversations.model import NewTurn
from contract.conversations_support import ascalar
from contract.test_inflight_resume import World, database
from contract.conversations_support import POLICY


@dataclass
class Rig:
    world: World
    outbox: Outbox

    async def began(self, text: str = "hi") -> tuple[Claim, int]:
        """A web conversation with one person turn that has work: (claim, conversation id)."""
        w = self.world
        conv = await services.get(Conversations).start(w.who.household_id, "chat", [w.who.id])
        said = await services.get(Conversations).add_turn(conv.id, NewTurn("person", text, w.who.id, "private",
                                                                          w.who.id))
        return await services.get(InFlight).begin(conv.id, said.id, "cp"), conv.id

    def push(self, conversation_id: int, thread: str, body: str) -> Pushed:
        return Pushed(self.world.who.household_id, thread, Outbound(conversation_id, "text", body))

    async def hers(self) -> int:
        return int(await ascalar(self.world.url, "SELECT count(*) FROM turns WHERE author = 'ashley'"))


@asynccontextmanager
async def rig(world: World) -> AsyncGenerator[Rig]:
    async with database(world) as db:
        outbox = PostgresOutbox(db, 600.0, POLICY)
        services.register(Outbox, outbox)
        try:
            yield Rig(world, outbox)
        finally:
            services.unregister(Outbox)
