"""The statements more than one of `PostgresConversations`' methods runs, each inside the caller's transaction."""

import logging
from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from .. import logs
from .conversations import ConversationClosed, ConversationNotFound, RefusedTurn, Unhanded
from .model import Channel, Conversation, Kind, NewTurn, Turn, unhanded
from .policy import Policy
from .postgres_rows import KINDS, TURN_COLUMNS, conversation_from, turn_from

Connection = AsyncConnection[tuple[Any, ...]]
log = logging.getLogger("ashley.conversations")


def checked(turn: NewTurn) -> None:
    """Raises ValueError for a turn no conversation stores."""
    if turn.author != "person" and turn.speaker_id is not None:
        raise ValueError("only a person's turn has a speaker")
    if turn.author != "ashley" and turn.follows:
        raise ValueError("only her turns are followed by an answer")
    if turn.author != "ashley" and turn.answers is not None:
        raise ValueError("only her turns answer a turn")
    if turn.author == "ashley" and turn.source is not None:
        raise ValueError("only a person's turn has a source")
    if turn.author != "person" and turn.carried_from is not None:
        raise ValueError("only a person's turn carries another")
    if turn.author != "ashley" and turn.continued_on is not None:
        raise ValueError("only her turns continue on a bench")
    if turn.author != "person" and turn.attachment is not None:
        raise ValueError("only a person's turn has an attachment")
    if turn.attachment is not None and not turn.attachment.text.strip():
        raise ValueError("an attachment has text")
    if not turn.text.strip():
        raise ValueError("a turn has text")
    if turn.spoken is not None and (turn.author != "ashley" or not turn.spoken.strip()):
        raise RefusedTurn("only her turns have a voice, and not a blank one")
    if turn.receipts is not None and turn.author != "ashley":
        raise RefusedTurn("only her turns have receipts")


async def insert_turn(conn: Connection, policy: Policy, conversation_id: int, turn: NewTurn) -> Turn:
    """`turn` added to the conversation, timed by the database's clock once the conversation's row is locked, which
    marks the conversation active and its speaker a participant; the turn of the household already stored with its
    `source`, with nothing written, when there is one. Raises ConversationNotFound; ConversationClosed when `policy` says
    it has closed."""
    cur = await conn.execute(
        "SELECT household_id, kind, last_activity_at, clock_timestamp() FROM conversations "
        "WHERE id = %s FOR UPDATE",
        (conversation_id,),
    )
    found = await cur.fetchone()
    if found is None:
        raise ConversationNotFound(conversation_id)
    household_id, kind, last, now = found
    if (known := await _stored_once(conn, household_id, turn)) is not None:
        return known
    if policy.state_of(KINDS[kind], last, now) == "closed":
        logs.info(log, "conversation.turn_refused", conversation=conversation_id, reason="closed")
        raise ConversationClosed(conversation_id)
    await all_handed(conn, conversation_id, turn)
    cur = await conn.execute(
        f"INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, at, visibility, "
        f"owner_id, follows, answers, source, carried_from, continued_on, attachment_title, attachment, spoken, receipts) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING "
        f"RETURNING {TURN_COLUMNS}",
        (conversation_id, household_id, turn.author, turn.speaker_id, turn.text, now, turn.heard,
         turn.owner_id, turn.follows, turn.answers, turn.source, turn.carried_from, turn.continued_on,
         None if turn.attachment is None else turn.attachment.title,
         None if turn.attachment is None else turn.attachment.text, turn.spoken,
         None if turn.receipts is None else Jsonb(turn.receipts.to_json())),
    )
    stored = await cur.fetchone()
    if stored is None:
        known = await _stored_once(conn, household_id, turn)
        assert known is not None
        return known
    assert stored is not None
    await conn.execute("UPDATE conversations SET last_activity_at = %s WHERE id = %s", (now, conversation_id))
    if turn.speaker_id is not None:
        await conn.execute(
            "INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (conversation_id, household_id, turn.speaker_id),
        )
    return turn_from(stored)


async def all_handed(conn: Connection, conversation_id: int, turn: NewTurn) -> None:
    """Raises Unhanded when `turn` carries `handed` and a person turn after the one it answers was not handed it."""
    if turn.handed is None or turn.answers is None:
        return
    cur = await conn.execute(f"SELECT {TURN_COLUMNS} FROM turns WHERE conversation_id = %s AND id > %s "
                             "AND author = 'person' ORDER BY id", (conversation_id, turn.answers))
    if unhanded([turn_from(r) for r in await cur.fetchall()], turn.answers, turn.handed):
        logs.info(log, "conversation.turn_refused", conversation=conversation_id, reason="unhanded")
        raise Unhanded()


async def _stored_once(conn: Connection, household_id: int, turn: NewTurn) -> Turn | None:
    """The turn already stored with this turn's `source` (of the household) or `carried_from`, if it has one."""
    if turn.source is not None:
        cur = await conn.execute(f"SELECT {TURN_COLUMNS} FROM turns WHERE household_id = %s AND source = %s",
                                 (household_id, turn.source))
    elif turn.carried_from is not None:
        cur = await conn.execute(f"SELECT {TURN_COLUMNS} FROM turns WHERE carried_from = %s", (turn.carried_from,))
    else:
        return None
    found = await cur.fetchone()
    return None if found is None else turn_from(found)


async def insert_conversation(conn: Connection, household_id: int, kind: Kind, people: list[int],
                              remembered: bool, channel: Channel | None, place: str | None,
                              thread: str | None = None) -> Conversation:
    """A new conversation with `people` (distinct) and no turns, state `open`, started on `thread` if it has one."""
    cur = await conn.execute(
        "INSERT INTO conversations (household_id, kind, remembered, channel, place, thread) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, household_id, kind, started_at, last_activity_at",
        (household_id, kind, remembered, channel, place, thread),
    )
    row = await cur.fetchone()
    assert row is not None
    await conn.execute(
        "INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
        "SELECT %s, %s, unnest(%s::bigint[])",
        (row[0], household_id, people),
    )
    return conversation_from(row, frozenset(people), (), "open", channel, place)


async def read_conversation(conn: Connection, policy: Policy, conversation_id: int,
                            lock: Literal["", "FOR SHARE"] = "") -> Conversation | None:
    """The conversation with its participants and turns, its state by the database's clock; None when there is none.
    `lock` is appended to the conversation's SELECT (`FOR SHARE`)."""
    cur = await conn.execute(
        "SELECT id, household_id, kind, started_at, last_activity_at, clock_timestamp(), channel, place "
        f"FROM conversations WHERE id = %s {lock}",
        (conversation_id,),
    )
    row = await cur.fetchone()
    if row is None:
        return None
    cur = await conn.execute(
        "SELECT person_id FROM conversation_participants WHERE conversation_id = %s", (conversation_id,)
    )
    participants = frozenset(r[0] for r in await cur.fetchall())
    cur = await conn.execute(
        f"SELECT {TURN_COLUMNS} FROM turns WHERE conversation_id = %s ORDER BY id", (conversation_id,)
    )
    turns = tuple(turn_from(r) for r in await cur.fetchall())
    state = policy.state_of(KINDS[row[2]], row[4], row[5])
    return conversation_from(row[:5], participants, turns, state, row[6], row[7])


async def spoken_of(conn: Connection, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
    """The `spoken` of turn `turn_id` when it is in a conversation of the household that `thread` carries and was stored
    at most `within_s` seconds ago by the database's clock; None otherwise."""
    cur = await conn.execute(
        "SELECT t.spoken FROM turns t JOIN conversation_threads c ON c.conversation_id = t.conversation_id "
        "WHERE t.id = %s AND t.household_id = %s AND c.household_id = %s AND c.thread = %s "
        "AND t.spoken IS NOT NULL AND t.at >= clock_timestamp() - make_interval(secs => %s::double precision)",
        (turn_id, household_id, household_id, thread, within_s))
    row = await cur.fetchone()
    return None if row is None else row[0]
