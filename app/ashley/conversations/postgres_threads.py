"""Which conversation a thread carries, inside the caller's transaction."""

from .model import Channel, Conversation, Kind
from .policy import Policy
from .postgres_queries import Connection, insert_conversation, read_conversation


class Raced(Exception):
    """Another call pointed this thread at a conversation first; the transaction must roll back and be tried again,
    when the thread's row exists and can be locked."""


async def carried(conn: Connection, policy: Policy, household_id: int, thread: str, kind: Kind,
                  people: list[int], remembered: bool, channel: Channel | None,
                  place: str | None) -> tuple[Conversation, bool]:
    """The conversation for the next turn on `thread`, and whether it was started now. Raises Raced."""
    cur = await conn.execute(
        "SELECT household_id, conversation_id FROM conversation_threads WHERE thread = %s FOR UPDATE", (thread,)
    )
    row = await cur.fetchone()
    if row is not None and row[0] == household_id:
        # FOR SHARE holds off add_turn, so the turns read agree with last_activity_at and the state.
        last = await read_conversation(conn, policy, row[1], "FOR SHARE")
        if last is not None and last.state != "closed":
            return last, False
    made = await insert_conversation(conn, household_id, kind, people, remembered, channel, place, thread)
    if row is None:
        await _point_new(conn, thread, made)
    else:
        await conn.execute(
            "UPDATE conversation_threads SET household_id = %s, conversation_id = %s, updated_at = now() "
            "WHERE thread = %s",
            (household_id, made.id, thread),
        )
    return made, True


async def _point_new(conn: Connection, thread: str, made: Conversation) -> None:
    cur = await conn.execute(
        "INSERT INTO conversation_threads (thread, household_id, conversation_id) VALUES (%s, %s, %s) "
        "ON CONFLICT (thread) DO NOTHING RETURNING thread",
        (thread, made.household_id, made.id),
    )
    if await cur.fetchone() is None:
        raise Raced(thread)
