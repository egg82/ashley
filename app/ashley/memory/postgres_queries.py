"""The statements `PostgresMemory` runs, each inside the caller's transaction, and rows to values."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, get_args

from psycopg import AsyncConnection

from ..conversations.model import Channel
from ..conversations.model import Kind as ConversationKind
from ..hearing import MAY_HEAR
from .model import Asker, Fact, Held, Kind, NewFact, Recalled, Replaced, Source, Visibility

Connection = AsyncConnection[tuple[Any, ...]]

VISIBILITIES: dict[str, Visibility] = {v: v for v in get_args(Visibility)}
KINDS: dict[str, Kind] = {k: k for k in get_args(Kind)}
PRIVATE_KINDS: frozenset[Kind] = frozenset({"health"})


@dataclass(frozen=True)
class Vector:
    """One embedding and the model that made it, as the statements take them."""

    values: Sequence[float]
    model: str

    @property
    def literal(self) -> str:
        """The vector as pgvector reads it from text."""
        return "[" + ",".join(repr(x) for x in self.values) + "]"


_COLUMNS = ("id, household_id, about_id, owner_id, visibility, kind, standing, text, source_conversation_id, "
            "valid_from, valid_to, superseded_by")

_HYBRID_HEAD = f"""
    WITH q AS (SELECT replace(plainto_tsquery('english', %(query)s)::text, ' & ', ' | ')::tsquery AS q),
    visible AS (
        SELECT {_COLUMNS}, search, embedding, embedding_model, """

# `visible` is where who may hear what is decided, in the WHERE clause, before anything is ranked. The text matches
# come first, by rank; the vector-only matches follow, by cosine distance, among facts embedded by the query's model.
# A query with no vector (the embedder was down) has no vector matches.
_HYBRID_TAIL = f"""
    ),
    by_text AS (
        SELECT v.*, -ts_rank(v.search, q.q) AS score FROM visible v, q WHERE v.search @@ q.q
        ORDER BY score, v.id DESC LIMIT %(limit)s),
    by_vector AS (
        SELECT v.*, v.embedding <=> %(vector)s::vector AS score FROM visible v
        WHERE %(vector)s::vector IS NOT NULL AND v.embedding_model = %(model)s
        ORDER BY score, v.id DESC LIMIT %(vector_k)s)
    SELECT {_COLUMNS}, volunteerable, 1 AS source, score FROM by_text
    UNION ALL
    SELECT {_COLUMNS}, volunteerable, 2, score FROM by_vector WHERE id NOT IN (SELECT id FROM by_text)
    ORDER BY source, score, id DESC
"""

# An unknown speaker gets shared facts; a known one also gets discreet facts, and private ones only when they own them
# and alone hear the reply. Recall, profile and `held` all filter by this.
_VISIBLE_TO_ASKER = f"""household_id = %(household)s
          AND valid_to IS NULL
          AND {MAY_HEAR}"""
_VOLUNTEERABLE = "(visibility = 'shared' OR coalesce(owner_id = %(speaker)s::bigint, false))"

# Standing facts reach the reply through `profile`, so recall leaves them out.
_RECALL = f"""{_HYBRID_HEAD}{_VOLUNTEERABLE} AS volunteerable
        FROM facts
        WHERE {_VISIBLE_TO_ASKER} AND NOT standing{_HYBRID_TAIL}"""

_PROFILE = f"""SELECT {_COLUMNS}, {_VOLUNTEERABLE} AS volunteerable FROM facts
        WHERE {_VISIBLE_TO_ASKER} AND standing ORDER BY id"""

# The write job's candidates: every visibility, since nobody hears them.
_SIMILAR = f"""{_HYBRID_HEAD}true AS volunteerable
        FROM facts WHERE household_id = %(household)s AND valid_to IS NULL{_HYBRID_TAIL}"""


def _utc(moment: datetime | None) -> datetime | None:
    return None if moment is None else moment.astimezone(UTC)


def _fact_from(row: tuple[Any, ...]) -> Fact:
    valid_from = _utc(row[9])
    assert valid_from is not None
    return Fact(row[0], row[1], row[2], row[3], VISIBILITIES[row[4]], KINDS[row[5]], row[6], row[7], row[8],
                valid_from, _utc(row[10]), row[11])


@dataclass(frozen=True)
class Found:
    """What a recall found: `recalled`, the text matches first and then the matches only the vector found, of which
    `by_text` are text matches."""

    recalled: tuple[Recalled, ...]
    by_text: int


def _params(vector: Vector | None, limit: int, vector_k: int) -> dict[str, Any]:
    return {"vector": None if vector is None else vector.literal, "model": None if vector is None else vector.model,
            "limit": limit, "vector_k": vector_k}


async def recall(conn: Connection, asker: Asker, query: str, limit: int, vector_k: int,
                 vector: Vector | None) -> Found:
    """The current facts `asker` may hear that match any word of `query`, best match first (every word counts on its
    own: a question rarely shares all its words with the fact that answers it), at most `limit` of them, then up to
    `vector_k` more that `vector`, the embedding of `query`, finds nearest, nearest first."""
    cur = await conn.execute(_RECALL, {
        "query": query, "household": asker.household_id, "speaker": asker.speaker_id,
        "owner_only": asker.owner_only, **_params(vector, limit, vector_k),
    })
    rows = await cur.fetchall()
    return Found(tuple(Recalled(_fact_from(r), r[12]) for r in rows), sum(1 for r in rows if r[13] == 1))


async def profile(conn: Connection, asker: Asker) -> tuple[Recalled, ...]:
    """The household's current standing facts `asker` may hear, by id."""
    cur = await conn.execute(_PROFILE, {"household": asker.household_id, "speaker": asker.speaker_id,
                                        "owner_only": asker.owner_only})
    return tuple(Recalled(_fact_from(r), r[12]) for r in await cur.fetchall())


async def similar(conn: Connection, household_id: int, query: str, limit: int, vector_k: int,
                  vector: Vector | None) -> tuple[Fact, ...]:
    """`recall` over the household's current facts of every visibility."""
    cur = await conn.execute(_SIMILAR, {"query": query, "household": household_id,
                                        **_params(vector, limit, vector_k)})
    return tuple(_fact_from(r) for r in await cur.fetchall())


def stored_standing(fact: NewFact) -> bool:
    """A `diet` fact is always standing."""
    return fact.standing or fact.kind == "diet"


def stored_owner(fact: NewFact) -> int | None:
    """Money is the household's unless its owner said who may know."""
    return None if fact.kind == "finance" and not fact.visibility_stated else fact.owner_id


def stored_visibility(fact: NewFact) -> Visibility:
    """Household money is `members` and any other household fact shared; health is private unless its owner said who
    may know."""
    if stored_owner(fact) is None:
        return "members" if fact.kind == "finance" else "shared"
    return "private" if fact.kind in PRIVATE_KINDS and not fact.visibility_stated else fact.visibility


async def insert(conn: Connection, household_id: int, conversation_id: int, fact: NewFact, at: datetime,
                 vector: Vector | None) -> int:
    cur = await conn.execute(
        "INSERT INTO facts (household_id, about_id, owner_id, visibility, visibility_stated, kind, standing, text, "
        "source_conversation_id, source_turn_id, valid_from, embedding, embedding_model) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s) RETURNING id",
        (household_id, fact.about_id, stored_owner(fact), stored_visibility(fact), fact.visibility_stated, fact.kind,
         stored_standing(fact), fact.text, conversation_id, fact.source_turn_id, at,
         None if vector is None else vector.literal, None if vector is None else vector.model),
    )
    row = await cur.fetchone()
    assert row is not None
    return int(row[0])


async def close(conn: Connection, household_id: int, target: int, at: datetime, successor: int | None) -> bool:
    """Closes `target` if it is a current fact of the household; False when it is not."""
    cur = await conn.execute(
        "UPDATE facts SET valid_to = %s, superseded_by = %s "
        "WHERE id = %s AND household_id = %s AND valid_to IS NULL RETURNING id",
        (at, successor, target, household_id),
    )
    return await cur.fetchone() is not None


async def forget(conn: Connection, household_id: int, target: int) -> int | None:
    """Deletes `target` and every fact it superseded, however far back; the count deleted, or None when `target` is
    not a current fact of the household."""
    cur = await conn.execute(
        "SELECT id FROM facts WHERE id = %s AND household_id = %s AND valid_to IS NULL FOR UPDATE",
        (target, household_id),
    )
    if await cur.fetchone() is None:
        return None
    cur = await conn.execute(
        "WITH RECURSIVE chain (id) AS ("
        " SELECT %s::bigint"
        " UNION ALL SELECT f.id FROM facts f JOIN chain c ON f.superseded_by = c.id"
        ") DELETE FROM facts WHERE id IN (SELECT id FROM chain) RETURNING id",
        (target,),
    )
    return len(await cur.fetchall())


_QUALIFIED = ", ".join("f." + name.strip() for name in _COLUMNS.split(","))

# The facts that concern the person (about them, theirs, the household's, or any member's household money), as recall filters them for that person
# alone; the fact each replaced, under the same filter; and its source conversation.
_HELD = f"""
    SELECT {_QUALIFIED}, p.text, p.valid_to, c.kind, c.started_at, c.channel, c.place,
           EXISTS (SELECT 1 FROM conversation_participants cp
                   WHERE cp.conversation_id = f.source_conversation_id AND cp.person_id = %(speaker)s) AS took_part
    FROM (SELECT {_COLUMNS} FROM facts
          WHERE {_VISIBLE_TO_ASKER}
            AND (owner_id = %(speaker)s OR about_id = %(speaker)s OR (owner_id IS NULL AND (about_id IS NULL OR visibility = 'members')))
            AND (%(fact)s::bigint IS NULL OR id = %(fact)s::bigint)) f
    JOIN conversations c ON c.id = f.source_conversation_id
    LEFT JOIN LATERAL (SELECT text, valid_to FROM facts WHERE superseded_by = f.id AND {MAY_HEAR}) p ON true
    ORDER BY f.valid_from DESC, f.id DESC
"""
CHANNELS: dict[str, Channel] = {c: c for c in get_args(Channel)}
CONVERSATION_KINDS: dict[str, ConversationKind] = {k: k for k in get_args(ConversationKind)}


def _held_from(row: tuple[Any, ...]) -> Held:
    text, valid_to, kind, started_at, channel, place, took_part = row[12:]
    replaced = None if text is None else Replaced(text, valid_to.astimezone(UTC))
    source = Source(row[8], CONVERSATION_KINDS[kind], started_at.astimezone(UTC), took_part,
                    CHANNELS.get(channel), place)
    return Held(_fact_from(row), replaced, source)


async def held(conn: Connection, household_id: int, person_id: int, fact_id: int | None) -> tuple[Held, ...]:
    cur = await conn.execute(_HELD, {"household": household_id, "speaker": person_id, "owner_only": True,
                                     "fact": fact_id})
    return tuple(map(_held_from, await cur.fetchall()))


async def by_ids(conn: Connection, ids: Sequence[int]) -> dict[int, Fact]:
    """The rows for `ids` whatever their validity; an id with no row (forgotten) is absent."""
    cur = await conn.execute(f"SELECT {_COLUMNS} FROM facts WHERE id = ANY(%s)", (list(ids),))
    return {fact.id: fact for fact in map(_fact_from, await cur.fetchall())}


async def writers(conn: Connection, conversation_id: int) -> tuple[tuple[str, str, str, str], ...]:
    """`(at, provider, model, outcome)` of each `memory_write` call the spend ledger holds for the conversation,
    oldest first, `at` as the log writes a time."""
    cur = await conn.execute(
        "SELECT to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.MS\"Z\"'), provider, model, outcome "
        "FROM inference_calls WHERE task = 'memory_write' AND conversation_id = %s ORDER BY at, id",
        (conversation_id,))
    return tuple((at, provider, model, outcome) for at, provider, model, outcome in await cur.fetchall())
