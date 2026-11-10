"""The outbox in Postgres, table `outbox`. A take deletes what it returns, so two pods never deliver one reply. An
answer is queued in the transaction that stores her turn and ends its work (`postgres_inflight.finished`).

Logs `conversation.turn` with the conversation, turn and author once an answer is stored, and `outbox.stale_dropped`
with the reply's id, conversation and age_ms when a take removes one older than `stale_s` unsent (her turn was stored
with it, so the answer stays on the thread)."""

import logging
from collections.abc import Callable, Sequence

import psycopg
from psycopg.types.json import Jsonb

from .. import logs, services
from ..conversations.inflight import Claim, InFlight
from ..conversations.model import NewTurn, Receipts, Turn
from ..conversations.policy import Policy
from ..conversations.postgres_inflight import finished, translated
from ..conversations.postgres_queries import Connection, checked
from ..db.database import Database, DatabaseUnavailable
from .model import Outbound
from .outbox import Later, Outbox, OutboxUnavailable, Pushed

log = logging.getLogger("ashley.conversations")


class PostgresOutbox(Outbox):
    def __init__(self, database: Database, stale_s: float, policy: Policy) -> None:
        self._database = database
        self._stale_s = stale_s
        self._policy = policy

    async def add(self, household_id: int, thread: str, outbound: Outbound) -> int:
        try:
            async with self._database.connection() as conn:
                return await _queued(conn, Pushed(household_id, thread, outbound))
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise OutboxUnavailable("database unreachable") from e

    async def answer(self, claim: Claim, turn: NewTurn, pushed: Sequence[Pushed],
                     after: Callable[[Turn], str] | None = None) -> Turn:
        checked(turn)
        with translated():
            async with self._database.connection() as conn:
                stored = await finished(conn, self._policy, claim, turn, services.get(InFlight).claim_s, after)
                for p in pushed:
                    await _queued(conn, p)
        logs.info(log, "conversation.turn", conversation=claim.conversation_id, turn=stored.id, author=turn.author)
        return stored

    async def take(self, prefix: str) -> list[Later]:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "DELETE FROM outbox WHERE starts_with(thread, %s) RETURNING id, household_id, thread, "
                    "conversation_id, medium, body, agree, receipts, (extract(epoch FROM clock_timestamp() - created_at) * 1000)::bigint",
                    (prefix,),
                )
                rows = await cur.fetchall()
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise OutboxUnavailable("database unreachable") from e
        fresh = [r for r in rows if r[8] <= self._stale_s * 1000]
        for r in rows:
            if r[8] > self._stale_s * 1000:
                logs.warning(log, "outbox.stale_dropped", id=r[0], conversation=r[3], age_ms=r[8])
        return [Later(r[0], r[1], r[2], Outbound(r[3], r[4], r[5], agree=r[6],
                                                 receipts=None if r[7] is None else Receipts.from_json(r[7])), r[8])
                for r in sorted(fresh, key=lambda r: r[0])]


async def _queued(conn: Connection, pushed: Pushed) -> int:
    outbound = pushed.outbound
    cur = await conn.execute(
        "INSERT INTO outbox (household_id, thread, conversation_id, medium, body, agree, receipts) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (pushed.household_id, pushed.thread, outbound.conversation_id, outbound.medium, outbound.body, outbound.agree,
         None if outbound.receipts is None else Jsonb(outbound.receipts.to_json())),
    )
    row = await cur.fetchone()
    assert row is not None
    return row[0]
