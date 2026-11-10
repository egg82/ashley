"""Helpers for the blind hybrid-memory contract tests: an `Inference` whose embeddings the test dictates, and
PostgresMemory over a pool with that inference registered through the locator."""

import math
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import psycopg
from ashley import services
from ashley.conversations.model import Conversation, Turn
from ashley.inference.embedding import EmbedRole, Embedded
from ashley.inference.inference import Inference, InferenceUnavailable, NullInference
from ashley.memory.model import NewFact, Visibility
from ashley.memory.postgres import PostgresMemory
from ashley.memory.recall_policy import RecallPolicy

from memory_support import pool

DIMENSIONS = 768
AT = datetime(2026, 3, 1, tzinfo=UTC)
LATER = AT + timedelta(days=2)


def unit(weights: Mapping[int, float]) -> tuple[float, ...]:
    values = [0.0] * DIMENSIONS
    for dimension, weight in weights.items():
        values[dimension] = weight
    norm = math.sqrt(sum(x * x for x in values))
    return tuple(x / norm for x in values)


class Dictated(NullInference):
    """Embeds a text as `table` says (text -> {dimension: weight}), or on the last dimension alone when it is not
    listed. Raises InferenceUnavailable while `down`. Records the role of every call."""

    def __init__(self, table: Mapping[str, Mapping[int, float]], model: str = "fake-1") -> None:
        self.table = table
        self.model = model
        self.down = False
        self.roles: list[EmbedRole] = []

    def vector(self, text: str) -> tuple[float, ...]:
        return unit(self.table.get(text, {DIMENSIONS - 1: 1.0}))

    async def embed(self, texts: Sequence[str], role: EmbedRole, *, conversation_id: int | None = None) -> Embedded:
        if self.down:
            raise InferenceUnavailable("down")
        self.roles.append(role)
        return Embedded(tuple(self.vector(t) for t in texts), self.model)


@asynccontextmanager
async def memory_with(url: str, inference: Inference, policy: RecallPolicy | None = None) -> AsyncGenerator[PostgresMemory]:
    services.register(Inference, inference)
    try:
        async with pool(url) as db:
            yield PostgresMemory(db, policy)
    finally:
        services.unregister(Inference)


def fact(text: str, owner: int | None = None, visibility: Visibility = "shared") -> NewFact:
    return NewFact(owner, owner, visibility, True, "other", False, text)


def rows(url: str, query: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(query.encode(), params).fetchall()


def distance_to(url: str, fact_id: int, vector: tuple[float, ...]) -> float | None:
    """Cosine distance between the fact's stored embedding and `vector`; None when it has none."""
    [(found,)] = rows(url, "SELECT embedding <=> %s::vector FROM facts WHERE id = %s",
                      ("[" + ",".join(repr(x) for x in vector) + "]", fact_id))
    return None if found is None else float(str(found))


def embedding_state(url: str, fact_id: int) -> tuple[bool, object]:
    [(has, model)] = rows(url, "SELECT embedding IS NOT NULL, embedding_model FROM facts WHERE id = %s", (fact_id,))
    return bool(has), model


def conversation_of(household_id: int, conversation_id: int, said: Sequence[tuple[str, str]]) -> Conversation:
    """A conversation value with turns `said` as (author, text)."""
    turns = tuple(Turn(i + 1, "person" if a == "person" else "ashley", None, t, AT) for i, (a, t) in enumerate(said))
    return Conversation(conversation_id, household_id, "chat", frozenset(), AT, AT, "idle", turns)
