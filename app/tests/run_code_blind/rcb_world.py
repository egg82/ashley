"""A real Postgres with a household, a conversation and a person turn, and the Runs service over it."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.runs.model import NewRun
from ashley.runs.postgres import PostgresRuns
from contract.conversations_support import POLICY, household, person


@dataclass
class World:
    url: str
    home: int
    conversation: int
    turn: int
    runs: PostgresRuns

    def new(self, script: str = "print(1)", call_id: str = "call-1", stdin: str = "",
            files: dict[str, str] | None = None) -> NewRun:
        return NewRun(self.home, self.conversation, self.turn, call_id, "python", script, stdin, files or {})

    def rows(self) -> int:
        with psycopg.connect(self.url) as conn:
            row = conn.execute("SELECT count(*) FROM code_runs").fetchone()
        assert row is not None
        return int(row[0])


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        home = household(url)
        who = person(url, home)
        conversations = PostgresConversations(db, POLICY)
        conv = await conversations.for_thread(home, "t1", "chat", [who])
        turn = await conversations.add_turn(conv.id, NewTurn("person", "run it", who))
        yield World(url, home, conv.id, turn.id, PostgresRuns(db))
    finally:
        await db.close()


async def other_household(base: World) -> int:
    return household(base.url, "elsewhere")
