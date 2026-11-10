"""A person's conversations in Postgres, newest activity first, paged by keyset."""

from typing import Any

from psycopg import AsyncConnection

from .model import Cursor, Page
from .quiet import QUIET
from .policy import Policy
from .postgres_rows import KINDS, summary_from

Connection = AsyncConnection[tuple[Any, ...]]

_SHOWN = """t.conversation_id = c.id AND NOT (t.author = 'ashley' AND t.text = %(quiet)s)
      AND NOT EXISTS (SELECT 1 FROM turns q WHERE q.answers = t.id AND q.author = 'ashley' AND q.text = %(quiet)s)"""
"""The turns of conversation `c` a page shows (`ashley.conversations.quiet`)."""

_LISTED = f"""
    SELECT c.id, c.kind, c.started_at, c.last_activity_at, c.channel, c.place,
           (SELECT count(*) FROM turns t WHERE {_SHOWN}), clock_timestamp()
    FROM conversations c
    WHERE c.household_id = %(household)s
      AND EXISTS (SELECT 1 FROM conversation_participants cp
                  WHERE cp.conversation_id = c.id AND cp.person_id = %(person)s)
      AND EXISTS (SELECT 1 FROM turns t WHERE {_SHOWN})
      AND (%(thread)s::text IS NULL OR c.thread = %(thread)s)
      AND (%(at)s::timestamptz IS NULL OR (c.last_activity_at, c.id) < (%(at)s::timestamptz, %(id)s::bigint))
    ORDER BY c.last_activity_at DESC, c.id DESC
    LIMIT %(fetch)s
"""


async def listed(conn: Connection, policy: Policy, household_id: int, person_id: int, limit: int,
                 after: Cursor | None, thread: str | None) -> Page:
    """Up to `limit` summaries after `after`; one more row is read to know whether a page follows."""
    cur = await conn.execute(_LISTED, {
        "household": household_id, "person": person_id, "quiet": QUIET, "fetch": limit + 1, "thread": thread,
        "at": None if after is None else after.last_activity_at, "id": None if after is None else after.id})
    rows = await cur.fetchall()
    items = tuple(summary_from(r[:7], policy.state_of(KINDS[r[1]], r[3], r[7])) for r in rows[:limit])
    more = items[-1] if len(rows) > limit else None
    return Page(items, None if more is None else Cursor(more.last_activity_at, more.id))
