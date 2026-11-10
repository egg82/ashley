"""Conversations in Postgres. One transaction per call; every time and every state decision is the database's clock
(`clock_timestamp()`, read after the conversation's row is locked, so turns of one conversation are timed in the order
they commit)."""

import logging
from collections.abc import Iterable

from .. import logs
from ..db.database import Database
from .conversations import Conversations, ConversationsUnavailable
from .model import Carried, Channel, Conversation, Cursor, Hearer, Kind, NewTurn, Page, Turn
from .policy import Policy
from . import postgres_carried
from .postgres_errors import translated
from .postgres_listing import listed
from .postgres_queries import checked, insert_conversation, insert_turn, read_conversation, spoken_of
from .postgres_rows import KINDS, TURN_COLUMNS, turn_from
from .postgres_threads import Raced, carried

log = logging.getLogger("ashley.conversations")

# A call that loses the race to create a thread's row retries once, and then finds that row to lock.
_THREAD_ATTEMPTS = 2


class PostgresConversations(Conversations):
    def __init__(self, database: Database, policy: Policy) -> None:
        self._database = database
        self._policy = policy

    async def start(self, household_id: int, kind: Kind, participants: Iterable[int],
                    remembered: bool = True, channel: Channel | None = None,
                    place: str | None = None) -> Conversation:
        if kind not in KINDS:
            raise ValueError(f"unknown conversation kind: {kind!r}")
        people = sorted(set(participants))
        with translated():
            async with self._database.connection() as conn:
                made = await insert_conversation(conn, household_id, kind, people, remembered, channel, place)
        logs.info(log, "conversation.started", conversation=made.id, kind=kind, participants=len(people))
        return made

    async def add_turn(self, conversation_id: int, turn: NewTurn) -> Turn:
        checked(turn)
        with translated():
            async with self._database.connection() as conn:
                stored = await insert_turn(conn, self._policy, conversation_id, turn)
        logs.info(log, "conversation.turn", conversation=conversation_id, turn=stored.id, author=turn.author)
        return stored

    async def for_thread(self, household_id: int, thread: str, kind: Kind, participants: Iterable[int],
                         remembered: bool = True, channel: Channel | None = None,
                         place: str | None = None) -> Conversation:
        if not thread.strip():
            raise ValueError("a thread is named")
        if kind not in KINDS:
            raise ValueError(f"unknown conversation kind: {kind!r}")
        people = sorted(set(participants))
        for _ in range(_THREAD_ATTEMPTS):
            try:
                with translated():
                    async with self._database.connection() as conn:
                        found, started = await carried(conn, self._policy, household_id, thread, kind, people,
                                                       remembered, channel, place)
            except Raced:
                continue
            if started:
                logs.info(log, "conversation.started", conversation=found.id, kind=kind, participants=len(people))
            logs.info(log, "conversation.thread", conversation=found.id, outcome="started" if started else "continued")
            return found
        raise ConversationsUnavailable("the thread kept changing under the call")

    async def get(self, conversation_id: int) -> Conversation | None:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                return await read_conversation(conn, self._policy, conversation_id)

    async def on_thread(self, household_id: int, thread: str) -> Conversation | None:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cur = await conn.execute(
                    "SELECT conversation_id FROM conversation_threads WHERE thread = %s AND household_id = %s",
                    (thread, household_id),
                )
                row = await cur.fetchone()
                return None if row is None else await read_conversation(conn, self._policy, row[0])

    async def answer_to(self, household_id: int, source: str) -> Turn | None:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    f"SELECT {TURN_COLUMNS} FROM turns WHERE answers = (SELECT id FROM turns WHERE household_id = %s "
                    "AND source = %s) AND NOT follows ORDER BY id DESC LIMIT 1", (household_id, source))
                row = await cur.fetchone()
                return None if row is None else turn_from(row)

    async def of_person(self, household_id: int, person_id: int, limit: int, after: Cursor | None = None,
                        thread: str | None = None) -> Page:
        if limit < 1:
            raise ValueError("a page has at least one conversation")
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                page = await listed(conn, self._policy, household_id, person_id, limit, after, thread)
        logs.info(log, "conversation.listed", person=person_id, count=len(page.items), more=page.next is not None)
        return page

    async def carried(self, hearer: Hearer, conversation_id: int, before: int, query: str, recent: int,
                      relevant: int) -> Carried:
        if recent < 0 or relevant < 0:
            raise ValueError("a budget is not negative")
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                return await postgres_carried.carried(conn, hearer, conversation_id, before, query, recent, relevant)

    async def spoken(self, household_id: int, thread: str, turn_id: int, within_s: int) -> str | None:
        with translated():
            async with self._database.connection() as conn:
                return await spoken_of(conn, household_id, thread, turn_id, within_s)
