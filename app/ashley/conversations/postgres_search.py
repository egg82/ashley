"""Full-text search over the turns of a person's own conversations, in SQL (`Conversations.search`)."""

from typing import Any

from psycopg import AsyncConnection

from .model import Match
from .quiet import QUIET
from .postgres_rows import AUTHORS, utc

Connection = AsyncConnection[tuple[Any, ...]]

_SNIPPET = "'MaxFragments=1, MinWords=8, MaxWords=24, StartSel=\"\", StopSel=\"\"'"

_FOUND = f"""
    WITH q AS (SELECT plainto_tsquery('english', %(query)s) AS q)
    SELECT t.conversation_id, t.id, t.at, t.author, ts_headline('english', t.text, q.q, {_SNIPPET}),
           ts_rank(t.search, q.q) AS rank
    FROM turns t JOIN conversations c ON c.id = t.conversation_id, q
    WHERE t.household_id = %(household)s AND c.household_id = %(household)s AND NOT c.eval
      AND t.search @@ q.q
      AND EXISTS (SELECT 1 FROM conversation_participants cp
                  WHERE cp.conversation_id = c.id AND cp.person_id = %(person)s)
      AND (t.visibility <> 'private' OR t.owner_id IS NULL OR t.owner_id = %(person)s)
      AND NOT (t.author = 'ashley' AND t.text = %(quiet)s)
      AND NOT EXISTS (SELECT 1 FROM turns a WHERE a.answers = t.id AND a.author = 'ashley' AND a.text = %(quiet)s)
    ORDER BY rank DESC, t.id DESC
    LIMIT %(limit)s"""


async def found(conn: Connection, household_id: int, person_id: int, query: str, limit: int) -> tuple[Match, ...]:
    cur = await conn.execute(_FOUND, {"household": household_id, "person": person_id, "query": query,
                                      "quiet": QUIET, "limit": limit})
    return tuple(Match(r[0], r[1], utc(r[2]), AUTHORS[r[3]], r[4], float(r[5])) for r in await cur.fetchall())
