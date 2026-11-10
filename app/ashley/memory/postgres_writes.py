"""The write job's bookkeeping in `memory_writes`, each statement inside the caller's transaction."""

from collections.abc import Mapping

from ..conversations.model import Kind
from .model import Unwritten
from .postgres_queries import Connection

# A turn still to write is a person's, newer than the watermark, and, once the failures in a row reach the cap, newer
# than the turn the last failure was on. The EXISTS walks turns_by_conversation from the watermark forward, so a
# conversation already written costs one index probe.
_UNWRITTEN = """
    SELECT c.id, c.household_id, w.written_turn_id, (SELECT max(id) FROM turns n WHERE n.conversation_id = c.id)
    FROM conversations c
    JOIN unnest(%(kinds)s::text[], %(idle)s::float8[]) AS i (kind, idle_s) ON i.kind = c.kind
    LEFT JOIN memory_writes w ON w.conversation_id = c.id
    WHERE c.remembered
      AND c.last_activity_at <= clock_timestamp() - make_interval(secs => i.idle_s)
      AND EXISTS (
          SELECT 1 FROM turns t
          WHERE t.conversation_id = c.id AND t.author = 'person' AND t.id > coalesce(w.written_turn_id, 0)
            AND (coalesce(w.failures, 0) < %(max_failures)s OR t.id > w.failed_turn_id))
    ORDER BY c.last_activity_at, c.id
    LIMIT %(limit)s
"""


async def unwritten(conn: Connection, idle_after_s: Mapping[Kind, float], limit: int,
                    max_failures: int) -> tuple[Unwritten, ...]:
    kinds = list(idle_after_s)
    cur = await conn.execute(_UNWRITTEN, {
        "kinds": kinds, "idle": [float(idle_after_s[k]) for k in kinds], "max_failures": max_failures, "limit": limit,
    })
    return tuple(Unwritten(*row) for row in await cur.fetchall())


async def mark_written(conn: Connection, household_id: int, conversation_id: int, through: int,
                       from_through: int | None) -> bool:
    """Moves the watermark from `from_through` to `through` and clears the failures, taking the row's lock until the
    transaction ends; False, changing nothing, when the watermark is no longer `from_through` or is already at
    `through` or later. The lock is why a concurrent writer waits and then finds it moved."""
    cur = await conn.execute(
        "INSERT INTO memory_writes (conversation_id, household_id, written_turn_id) VALUES (%s, %s, %s) "
        "ON CONFLICT (conversation_id) DO UPDATE "
        "SET written_turn_id = excluded.written_turn_id, failures = 0, failed_turn_id = NULL "
        "WHERE memory_writes.written_turn_id IS NOT DISTINCT FROM %s "
        "AND (memory_writes.written_turn_id IS NULL OR memory_writes.written_turn_id < excluded.written_turn_id) "
        "RETURNING conversation_id",
        (conversation_id, household_id, through, from_through),
    )
    return await cur.fetchone() is not None


async def written_through(conn: Connection, conversation_id: int) -> int | None:
    cur = await conn.execute("SELECT written_turn_id FROM memory_writes WHERE conversation_id = %s", (conversation_id,))
    row = await cur.fetchone()
    return None if row is None else row[0]


async def write_failed(conn: Connection, household_id: int, conversation_id: int, through: int) -> int:
    cur = await conn.execute(
        "INSERT INTO memory_writes (conversation_id, household_id, failures, failed_turn_id) VALUES (%s, %s, 1, %s) "
        "ON CONFLICT (conversation_id) DO UPDATE "
        "SET failures = CASE WHEN memory_writes.failed_turn_id >= excluded.failed_turn_id "
        "                    THEN memory_writes.failures + 1 ELSE 1 END, "
        "    failed_turn_id = excluded.failed_turn_id "
        "RETURNING failures",
        (conversation_id, household_id, through),
    )
    row = await cur.fetchone()
    assert row is not None
    return int(row[0])
