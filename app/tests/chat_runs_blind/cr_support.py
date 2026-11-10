"""Support for the blind chat-run tests: turns and runs built by hand for the pure functions, and a Postgres world
with a household, a person, conversations and the Runs service."""

import asyncio
from collections.abc import AsyncGenerator, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from ashley.api.run_models import ChatRun
from ashley.conversations.model import NewTurn, Turn
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.runs.model import BenchRun, NewRun, Output, Run
from ashley.runs.postgres import PostgresRuns
from contract.conversations_support import POLICY, household, person

AT = datetime(2026, 10, 27, 19, 42, tzinfo=UTC)
OUT = Output("ran", 0, "out", "err", False, {"r.txt": "é"}, ("b.bin",))


def run_async[T](scenario: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(scenario, 30))


def turn(i: int, author: str, follows: bool = False, answers: int | None = None) -> Turn:
    """Turn `i`: `p` is a person's, `a` hers, `h` a held line of hers; `answers` the person turn hers answers."""
    return Turn(i, "person" if author == "p" else "ashley", 7 if author == "p" else None, f"t{i}",
                AT + timedelta(minutes=i), follows or author == "h", answers=answers)


def turns(shape: str) -> list[Turn]:
    """Turns numbered from 1 from a string such as `pha`: p person, h her held line, a her answer. Each of hers answers
    the person turn before it, if any."""
    asked: int | None = None
    built: list[Turn] = []
    for i, c in enumerate(shape, 1):
        asked = i if c == "p" else asked
        built.append(turn(i, c, answers=None if c == "p" else asked))
    return built


def run(run_id: int, turn_id: int | None, output: Output | None = OUT, conversation_id: int | None = 5,
        bench: BenchRun | None = None) -> Run:
    return Run(run_id, 10, conversation_id, turn_id, f"call-{run_id}", "python", f"script {run_id}", "in",
               {"a.txt": "x"}, AT, None if output is None else AT + timedelta(seconds=1), output, bench)


def ids(shown: Mapping[int, list[ChatRun]]) -> dict[int, list[int]]:
    """Answer turn id to the ids of the runs under it, leaving out answers with none."""
    return {k: [r.id for r in v] for k, v in shown.items() if v}


@dataclass
class World:
    url: str
    home: int
    who: int
    conversations: PostgresConversations
    runs: PostgresRuns

    async def conversation(self, thread: str, home: int | None = None) -> int:
        who = self.who if home is None else person(self.url, home)
        return (await self.conversations.for_thread(self.home if home is None else home, thread, "chat", [who])).id

    async def said(self, conversation_id: int, text: str = "run it") -> int:
        return (await self.conversations.add_turn(conversation_id, NewTurn("person", text, self.who))).id

    def new(self, conversation_id: int, turn_id: int, script: str = "print(1)", home: int | None = None) -> NewRun:
        return NewRun(self.home if home is None else home, conversation_id, turn_id, f"call-{script}", "python", script)

    def bench(self, seq: int = 1) -> BenchRun:
        """A bench of this household with Run command `seq` logged, and the BenchRun naming them."""
        with psycopg.connect(self.url, autocommit=True) as conn:
            row = conn.execute("SELECT id FROM benches WHERE household_id = %s", (self.home,)).fetchone()
            if row is None:
                row = conn.execute("INSERT INTO benches (household_id, owner_id, title) VALUES (%s, %s, 'b') "
                                   "RETURNING id", (self.home, self.who)).fetchone()
            assert row is not None
            conn.execute("INSERT INTO bench_commands (bench_id, household_id, seq, command, outcome, effect) "
                         "VALUES (%s, %s, %s, '{}', 'accepted', '{}')", (row[0], self.home, seq))
        return BenchRun(int(row[0]), seq, 1, 1)


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        home = household(url)
        yield World(url, home, person(url, home), PostgresConversations(db, POLICY), PostgresRuns(db))
    finally:
        await db.close()
