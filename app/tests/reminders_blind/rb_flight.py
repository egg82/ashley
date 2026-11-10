"""A real Conversations and PostgresInFlight over one migrated database, for the begin-versus-finish race."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from ashley.conversations.conversations import Conversations
from ashley.conversations.inflight import InFlight
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from contract.conversations_support import POLICY, household, person, scalar


@dataclass
class Rig:
    url: str
    home: int
    who: int
    conversations: Conversations
    inflight: InFlight

    async def said(self, thread: str) -> tuple[int, int]:
        """A conversation on `thread` with one person turn in it: (conversation id, that turn's id)."""
        conv = await self.conversations.for_thread(self.home, thread, "chat", [self.who])
        turn = await self.conversations.add_turn(conv.id, NewTurn("person", "hello", self.who))
        return conv.id, turn.id

    def rows(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM turn_work"))

    def hers(self) -> list[str]:
        got = scalar(self.url, "SELECT coalesce(string_agg(text, '|' ORDER BY id), '') FROM turns WHERE author = 'ashley'")
        return [t for t in str(got).split("|") if t]


@asynccontextmanager
async def rig(url: str, home: int | None = None, who: int | None = None) -> AsyncGenerator[Rig]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        house = home if home is not None else household(url)
        yield Rig(url, house, who if who is not None else person(url, house), PostgresConversations(db, POLICY),
                  PostgresInFlight(db, POLICY, 60.0))
    finally:
        await db.close()
