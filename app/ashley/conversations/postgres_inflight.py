"""`InFlight` in Postgres, table `turn_work`. A claim is the row's `holder`; once `claimed_until` has passed by the
database's clock, `orphaned` may give the row a new holder. Every write names the holder, so a runner whose work was
taken writes nothing.

Logs `inflight.orphaned` with the work's person turn and attempts each time a piece is claimed for a new runner,
`inflight.left` with the dropped work's person turn and the one it left work for, and `conversation.agreed` with the
conversation and person turn an agreed outcome is set on."""

import logging
import secrets
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import LiteralString

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from .inflight import Claim, ClaimLost, InFlight, InFlightUnavailable, Leaving, Orphan
from .model import AgreedOutcome, NewTurn, Turn, unhanded
from .policy import Policy
from .postgres_queries import Connection, checked, insert_turn
from .postgres_rows import TURN_COLUMNS, turn_from

log = logging.getLogger("ashley.conversations")

_UNTIL: LiteralString = "clock_timestamp() + make_interval(secs => %(claim_s)s)"
_ANSWERED: LiteralString = ("SELECT 1 FROM turns WHERE conversation_id = %(conversation)s AND answers = %(said)s "
                            "AND NOT follows")


@contextmanager
def translated() -> Generator[None]:
    """The database's failures as `InFlight` raises them."""
    try:
        yield
    except errors.UniqueViolation as e:
        raise ValueError("work for that turn already exists") from e
    except (DatabaseUnavailable, psycopg.OperationalError, errors.ReadOnlySqlTransaction) as e:
        raise InFlightUnavailable("database unreachable or not writable") from e


class PostgresInFlight(InFlight):
    def __init__(self, database: Database, policy: Policy, claim_s: float) -> None:
        self._database = database
        self._policy = policy
        self._claim_s = claim_s

    @property
    def claim_s(self) -> float:
        return self._claim_s

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        claim = Claim(said_id, conversation_id, _holder())
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "INSERT INTO turn_work (said_id, conversation_id, household_id, holder, claimed_until, checkpoint) "
                    "SELECT %(said)s, id, household_id, %(holder)s, " + _UNTIL + ", %(checkpoint)s FROM conversations "
                    "WHERE id = %(conversation)s AND NOT EXISTS (" + _ANSWERED + ")",
                    {"said": said_id, "conversation": conversation_id, "holder": claim.holder,
                     "claim_s": self._claim_s, "checkpoint": checkpoint})
                if cur.rowcount != 1:
                    raise ValueError("no conversation has that id, or her answer to that turn is stored")
                # The insert may have waited on a finish deleting the same row; its check read the snapshot from
                # before that wait, so the answer is looked for again, now that the finish has committed.
                cur = await conn.execute(_ANSWERED, {"said": said_id, "conversation": conversation_id})
                if await cur.fetchone() is not None:
                    raise ValueError("her answer to that turn is stored")
        return claim

    async def save(self, claim: Claim, checkpoint: str) -> None:
        await self._held("UPDATE turn_work SET checkpoint = %(checkpoint)s, claimed_until = " + _UNTIL, claim,
                         checkpoint=checkpoint)

    async def renew(self, claim: Claim) -> None:
        await self._held("UPDATE turn_work SET claimed_until = " + _UNTIL, claim)

    async def defer(self, claim: Claim, seconds: float) -> None:
        await self._held("UPDATE turn_work SET claimed_until = clock_timestamp() + make_interval(secs => %(secs)s)",
                         claim, secs=seconds)

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        checked(turn)
        with translated():
            async with self._database.connection() as conn:
                await _renewed(conn, claim, self._claim_s)
                stored = await insert_turn(conn, self._policy, claim.conversation_id, turn)
        logs.info(log, "conversation.turn", conversation=claim.conversation_id, turn=stored.id, author=turn.author)
        return stored

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        checked(turn)
        with translated():
            async with self._database.connection() as conn:
                stored = await finished(conn, self._policy, claim, turn, self._claim_s, after)
        logs.info(log, "conversation.turn", conversation=claim.conversation_id, turn=stored.id, author=turn.author)
        return stored

    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        with translated():
            async with self._database.connection() as conn:
                await _taken(conn, claim)
                await conn.execute("UPDATE turns SET agreed = %s WHERE id = %s AND author = 'person'",
                                   (Jsonb(outcome.to_json()), claim.said_id))
        logs.info(log, "conversation.agreed", conversation=claim.conversation_id, turn=claim.said_id)

    async def drop(self, claim: Claim) -> bool:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("DELETE FROM turn_work WHERE said_id = %s AND holder = %s",
                                         (claim.said_id, claim.holder))
                if cur.rowcount == 1:
                    return True
                cur = await conn.execute("SELECT 1 FROM turn_work WHERE said_id = %s", (claim.said_id,))
                return await cur.fetchone() is None

    async def drop_leaving(self, claim: Claim, leaving: Leaving) -> bool:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute("SELECT 1 FROM conversations WHERE id = %s FOR UPDATE", (leaving.conversation_id,))
                cur = await conn.execute("DELETE FROM turn_work WHERE said_id = %s AND holder = %s",
                                         (claim.said_id, claim.holder))
                if cur.rowcount != 1:
                    cur = await conn.execute("SELECT 1 FROM turn_work WHERE said_id = %s", (claim.said_id,))
                    return await cur.fetchone() is None
                left = await _left(conn, leaving)
                if left is not None:
                    await conn.execute(
                        "INSERT INTO turn_work (said_id, conversation_id, household_id, holder, claimed_until, "
                        "checkpoint) SELECT %s, id, household_id, %s, clock_timestamp(), %s FROM conversations "
                        "WHERE id = %s ON CONFLICT DO NOTHING",
                        (left.id, _holder(), leaving.seed(left), leaving.conversation_id))
        if left is not None:
            logs.info(log, "inflight.left", said=claim.said_id, left=left.id)
        return True

    async def orphaned(self, limit: int) -> list[Orphan]:
        holder = _holder()
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    f"UPDATE turn_work SET holder = %(holder)s, claimed_until = {_UNTIL}, attempts = attempts + 1 "
                    "WHERE said_id IN (SELECT said_id FROM turn_work WHERE claimed_until < clock_timestamp() "
                    "ORDER BY said_id LIMIT %(limit)s FOR UPDATE SKIP LOCKED) "
                    "RETURNING said_id, conversation_id, checkpoint, attempts, "
                    "extract(epoch FROM clock_timestamp() - (SELECT at FROM turns WHERE id = turn_work.said_id))::float8",
                    {"holder": holder, "claim_s": self._claim_s, "limit": limit})
                rows = await cur.fetchall()
        found = [Orphan(Claim(r[0], r[1], holder), r[2], r[3], r[4]) for r in sorted(rows, key=lambda r: r[0])]
        for orphan in found:
            logs.info(log, "inflight.orphaned", said=orphan.claim.said_id, attempts=orphan.attempts)
        return found

    async def working(self, conversation_id: int) -> frozenset[int]:
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    "SELECT said_id FROM turn_work w WHERE conversation_id = %(c)s AND NOT EXISTS (SELECT 1 FROM turns "
                    "WHERE conversation_id = w.conversation_id AND answers = w.said_id AND NOT follows) "
                    "UNION SELECT t.id FROM turn_work w JOIN turns t ON t.carried_from = w.said_id "
                    "WHERE t.conversation_id = %(c)s AND NOT EXISTS (SELECT 1 FROM turns "
                    "WHERE conversation_id = t.conversation_id AND answers = t.id AND NOT follows)",
                    {"c": conversation_id})
                return frozenset(r[0] for r in await cur.fetchall())

    async def _held(self, statement: LiteralString, claim: Claim, **values: object) -> None:
        """Run `statement` (an UPDATE of `turn_work`) on the claim's row while the claim holds it."""
        with translated():
            async with self._database.connection() as conn:
                cur = await conn.execute(
                    statement + " WHERE said_id = %(said)s AND holder = %(holder)s",
                    {"said": claim.said_id, "holder": claim.holder, "claim_s": self._claim_s, **values})
                if cur.rowcount != 1:
                    raise ClaimLost()


async def _renewed(conn: Connection, claim: Claim, claim_s: float) -> None:
    """Renew the claim while it holds the work; raises ClaimLost when it does not."""
    cur = await conn.execute("UPDATE turn_work SET claimed_until = " + _UNTIL + " WHERE said_id = %(said)s "
                             "AND holder = %(holder)s", {"said": claim.said_id, "holder": claim.holder, "claim_s": claim_s})
    if cur.rowcount != 1:
        raise ClaimLost()


async def finished(conn: Connection, policy: Policy, claim: Claim, turn: NewTurn, claim_s: float,
                   after: Callable[[Turn], str] | None = None) -> Turn:
    """`InFlight.finish` inside the caller's transaction, so another write can commit with it (`PostgresOutbox.answer`).
    `turn` is `checked` by the caller. Raises ClaimLost, ConversationClosed, ConversationNotFound."""
    if after is None:
        await _taken(conn, claim)
        return await insert_turn(conn, policy, claim.conversation_id, turn)
    await _renewed(conn, claim, claim_s)
    stored = await insert_turn(conn, policy, claim.conversation_id, turn)
    await conn.execute("UPDATE turn_work SET checkpoint = %s WHERE said_id = %s", (after(stored), claim.said_id))
    return stored


async def _taken(conn: Connection, claim: Claim) -> None:
    """Delete the claim's work while it holds it; raises ClaimLost when it does not."""
    cur = await conn.execute("DELETE FROM turn_work WHERE said_id = %s AND holder = %s", (claim.said_id, claim.holder))
    if cur.rowcount != 1:
        raise ClaimLost()


async def _left(conn: Connection, leaving: Leaving) -> Turn | None:
    """The oldest person turn `leaving` leaves without an answer, if any."""
    cur = await conn.execute("SELECT 1 FROM turns WHERE conversation_id = %s AND answers = %s AND NOT follows",
                             (leaving.conversation_id, leaving.after))
    if await cur.fetchone() is not None:
        return None
    cur = await conn.execute(f"SELECT {TURN_COLUMNS} FROM turns WHERE conversation_id = %s AND id > %s "
                             "AND author = 'person' ORDER BY id", (leaving.conversation_id, leaving.after))
    left = unhanded([turn_from(r) for r in await cur.fetchall()], leaving.after, ())
    return left[0] if left else None


def _holder() -> str:
    return secrets.token_hex(8)
