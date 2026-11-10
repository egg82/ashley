"""Support for the blind InFlight tests: a real Conversations and PostgresInFlight over one migrated database, and raw
SQL to age a claim, so no test waits for a clock."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import Claim, InFlight
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from contract.conversations_support import POLICY, aexecute, ascalar, household, person

CLAIM_S = 60.0


@dataclass
class Rig:
    url: str
    home: int
    who: int
    conversations: Conversations
    inflight: InFlight

    async def said(self, thread: str = "t1", text: str = "hello") -> tuple[int, int]:
        """A conversation on `thread` with one person turn in it: (conversation id, that turn's id)."""
        conv = await self.conversations.for_thread(self.home, thread, "chat", [self.who])
        turn = await self.conversations.add_turn(conv.id, NewTurn("person", text, self.who))
        return conv.id, turn.id

    async def begin(self, checkpoint: str = "cp0", thread: str = "t1") -> Claim:
        conv_id, said_id = await self.said(thread)
        return await self.inflight.begin(conv_id, said_id, checkpoint)

    async def expire(self, claim: Claim) -> None:
        """Run its claim out, by the database's clock."""
        await aexecute(self.url, "UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second' "
                                "WHERE said_id = %s", (claim.said_id,))

    async def lapse(self, claim: Claim, seconds_ago: float) -> None:
        """Run its claim out `seconds_ago` before now."""
        await aexecute(self.url, "UPDATE turn_work SET claimed_until = clock_timestamp() - %s::interval "
                                "WHERE said_id = %s", (f"{seconds_ago} seconds", claim.said_id))

    async def expire_all(self) -> None:
        await aexecute(self.url, "UPDATE turn_work SET claimed_until = clock_timestamp() - interval '1 second'", ())

    async def age(self, claim: Claim, seconds: float) -> None:
        """Make the person's turn `seconds` older."""
        await aexecute(self.url, "UPDATE turns SET at = at - %s::interval WHERE id = %s",
                       (f"{seconds} seconds", claim.said_id))

    async def rows(self) -> int:
        return int(await ascalar(self.url, "SELECT count(*) FROM turn_work"))

    async def hers(self) -> list[str]:
        got = await ascalar(self.url, "SELECT coalesce(string_agg(text, '|' ORDER BY id), '') FROM turns "
                                     "WHERE author = 'ashley'")
        return [t for t in str(got).split("|") if t]


@asynccontextmanager
async def rig(url: str, claim_s: float = CLAIM_S) -> AsyncGenerator[Rig]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        home = household(url)
        yield Rig(url, home, person(url, home), PostgresConversations(db, POLICY), PostgresInFlight(db, POLICY, claim_s))
    finally:
        await db.close()
