"""The turns a reply carries (`Conversations.carried`), inside the caller's transaction. Who may hear a turn is decided
in each statement's SQL by `MAY_HEAR`; a turn that fails it is only ever counted, never selected."""

from typing import Any, LiteralString

from ..hearing import MAY_HEAR
from .model import Carried, Hearer, Place, Turn
from .postgres_queries import Connection
from .postgres_rows import TURN_COLUMNS, turn_from

# Another conversation is carried only when she remembers it (an eval harness's is not).
_REMEMBERED = "(SELECT id FROM conversations WHERE household_id = %(household)s AND remembered)"

# The conversations whose turns are recent candidates: this one, and every remembered one the speaker took part in.
_SPEAKERS = f"""(conversation_id = %(conversation)s
               OR conversation_id IN (SELECT conversation_id FROM conversation_participants
                                      WHERE household_id = %(household)s AND person_id = %(speaker)s::bigint
                                        AND conversation_id IN {_REMEMBERED}))"""

_RECENT_CANDIDATES = f"""
    WITH candidates AS (
        SELECT {TURN_COLUMNS}, coalesce({MAY_HEAR}, false) AS may_hear FROM turns
        WHERE household_id = %(household)s AND id < %(before)s AND {_SPEAKERS})"""

# Each kept turn with the thread it was said on, and that thread's bench title when it is `bench:<id>`; the thread is
# NULL when it is the replying conversation's own or not recorded.
_KEPT = ", ".join(f"kept.{c.strip()}" for c in TURN_COLUMNS.split(","))

_RECENT = f"""{_RECENT_CANDIDATES},
    kept AS (SELECT * FROM candidates WHERE may_hear ORDER BY id DESC LIMIT %(recent)s)
    SELECT {_KEPT},
           CASE WHEN c.thread IS DISTINCT FROM (SELECT thread FROM conversations WHERE id = %(conversation)s)
                THEN c.thread END,
           b.title
    FROM kept JOIN conversations c ON c.id = kept.conversation_id
    LEFT JOIN benches b ON b.household_id = c.household_id AND b.owner_id IS NOT NULL
                       AND b.id = CASE WHEN c.thread ~ '^bench:[0-9]+$' THEN substr(c.thread, 7)::bigint END
    ORDER BY kept.id DESC"""

_RECENT_FILTERED = f"""{_RECENT_CANDIDATES}
    SELECT count(*) FROM candidates WHERE NOT may_hear AND id > %(oldest)s"""

_MATCHES = f"""
    WITH q AS (SELECT replace(plainto_tsquery('english', %(query)s)::text, ' & ', ' | ')::tsquery AS q),
    matches AS (
        SELECT {TURN_COLUMNS}, coalesce({MAY_HEAR}, false) AS may_hear, ts_rank(search, q.q) AS rank FROM turns, q
        WHERE household_id = %(household)s AND id < %(before)s AND search @@ q.q
          AND (conversation_id = %(conversation)s OR conversation_id IN {_REMEMBERED})
          AND NOT (id > %(oldest)s AND {_SPEAKERS}))"""

_RELEVANT = f"""{_MATCHES}
    SELECT {TURN_COLUMNS} FROM matches WHERE may_hear ORDER BY rank DESC, id DESC LIMIT %(relevant)s"""

_RELEVANT_FILTERED = f"""{_MATCHES}
    SELECT count(*) FROM matches WHERE NOT may_hear"""


async def carried(conn: Connection, hearer: Hearer, conversation_id: int, before: int, query: str, recent: int,
                  relevant: int) -> Carried:
    params: dict[str, Any] = {"household": hearer.household_id, "speaker": hearer.speaker_id,
                              "owner_only": hearer.owner_only, "before": before, "conversation": conversation_id}
    kept, places, window = await _recent(conn, params, recent)
    recent_filtered = 0 if recent == 0 else await _count(conn, _RECENT_FILTERED, {**params, "oldest": window})
    found, relevant_filtered = await _relevant(conn, {**params, "oldest": window}, query, relevant)
    return Carried(kept, found, recent_filtered + relevant_filtered, places)


async def _recent(conn: Connection, params: dict[str, Any],
                  recent: int) -> tuple[tuple[Turn, ...], dict[int, Place], int]:
    """The recent turns, where those said on another thread were said, and the id the recent window starts after:
    every candidate when fewer than `recent` were carried, none when `recent` is 0."""
    if recent == 0:
        return (), {}, params["before"]
    cur = await conn.execute(_RECENT, {**params, "recent": recent})
    rows = list(reversed(await cur.fetchall()))
    kept = tuple(turn_from(r) for r in rows)
    places = {t.id: Place(r[-2], r[-1]) for t, r in zip(kept, rows) if r[-2] is not None}
    return kept, places, kept[0].id - 1 if len(kept) == recent else 0


async def _relevant(conn: Connection, params: dict[str, Any], query: str,
                    relevant: int) -> tuple[tuple[Turn, ...], int]:
    """Matches of `query` outside the recent window, which `params["oldest"]` bounds."""
    if relevant == 0:
        return (), 0
    asked = {**params, "query": query, "relevant": relevant}
    cur = await conn.execute(_RELEVANT, asked)
    return tuple(turn_from(r) for r in await cur.fetchall()), await _count(conn, _RELEVANT_FILTERED, asked)


async def _count(conn: Connection, statement: LiteralString, params: dict[str, Any]) -> int:
    cur = await conn.execute(statement, params)
    row = await cur.fetchone()
    assert row is not None
    return int(row[0])
