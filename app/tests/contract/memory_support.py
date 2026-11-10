"""Helpers for the PostgresMemory tests: the households, people and conversations a fact may name, made with raw SQL,
and the service over a pool."""

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime

from ashley.db.pool import PoolDatabase
from ashley.memory.model import Op
from ashley.memory.postgres import PostgresMemory

from conversations_support import household, person, scalar


def conversation(url: str, household_id: int, kind: str = "chat") -> int:
    return int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, %s) RETURNING id",
                      (household_id, kind)))


def say(url: str, conversation_id: int, *turns: str, speaker: int | None = None) -> tuple[int, ...]:
    """Adds turns now, alternating person (first) and ashley; returns their ids. Moves the conversation's last
    activity to now, as the service does."""
    ids: list[int] = []
    for i, text in enumerate(turns):
        author = "person" if i % 2 == 0 else "ashley"
        ids.append(int(scalar(
            url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text) "
                 "SELECT id, household_id, %s, %s, %s FROM conversations WHERE id = %s RETURNING id",
            (author, speaker if author == "person" else None, text, conversation_id))))
    scalar(url, "UPDATE conversations SET last_activity_at = clock_timestamp() WHERE id = %s RETURNING id",
           (conversation_id,))
    return tuple(ids)


def recall_cast(url: str, people: dict[str, int], households: dict[str, int], person_household: dict[str, str]) -> None:
    """The rows `recall_cases.json` names, at the ids it names; a fresh database hands them out in order."""
    for name, wanted in sorted(households.items(), key=lambda kv: kv[1]):
        assert household(url, name) == wanted
    for name, wanted in sorted(people.items(), key=lambda kv: kv[1]):
        assert person(url, households[person_household[name]], name) == wanted


class ConversationsAsTheyCome(PostgresMemory):
    """The recall harness numbers its conversations 1, 2, 3... across households; this makes each one, in the household
    it is applied to, the first time it is named, so the facts' references hold."""

    def __init__(self, database: PoolDatabase, url: str) -> None:
        super().__init__(database)
        self._url = url
        self._made: set[int] = set()

    async def apply(self, household_id: int, conversation_id: int, ops: Sequence[Op], at: datetime,
                    written_through: int | None = None, written_from: int | None = None) -> tuple[int, ...]:
        if conversation_id not in self._made:
            made = scalar(self._url, "INSERT INTO conversations (id, household_id, kind) OVERRIDING SYSTEM VALUE "
                                     "VALUES (%s, %s, 'chat') RETURNING id", (conversation_id, household_id))
            self._made.add(made)
        return await super().apply(household_id, conversation_id, ops, at, written_through)


@asynccontextmanager
async def pool(url: str, connect_timeout_s: float = 5.0) -> AsyncGenerator[PoolDatabase]:
    db = PoolDatabase(url, connect_timeout_s=connect_timeout_s)
    await db.open()
    try:
        yield db
    finally:
        await db.close()
