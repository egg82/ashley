"""Proposals in Postgres: `proposals`, one row per proposal, deleted when taken or past its limit."""

from datetime import UTC, datetime
from typing import Any, LiteralString

import psycopg
from psycopg.types.json import Jsonb

from ..db.database import Database, DatabaseUnavailable
from .proposal_payloads import OUTSIDE, Payload, Topic, check, encode
from .proposals import Proposal, ProposalRefused, Proposals, ProposalsUnavailable, refusal


class PostgresProposals(Proposals):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        check(proposal.payload)
        topic, stored = encode(proposal.payload)
        where = "*" if topic == OUTSIDE.name else proposal.conversation_id
        try:
            async with self._database.connection() as conn:
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                                   (f"proposal:{proposal.made_by}:{where}:{topic}",))
                await conn.execute("DELETE FROM proposals WHERE made_by = %s AND topic = %s "
                                   "AND (%s OR conversation_id = %s)",
                                   (proposal.made_by, topic, topic == OUTSIDE.name, proposal.conversation_id))
                cur = await conn.execute(
                    "INSERT INTO proposals (household_id, made_by, conversation_id, turn_id, topic, payload, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (proposal.household_id, proposal.made_by, proposal.conversation_id, proposal.turn_id, topic, Jsonb(stored),
                     proposal.proposed_at))
                made = await cur.fetchone()
                await conn.execute("DELETE FROM proposals WHERE topic = %s AND created_at < now() - make_interval(secs => %s)",
                                   (topic, ttl_s))
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise ProposalsUnavailable("database unavailable") from e
        if made is None:
            raise ProposalsUnavailable("the proposal was not stored")
        return int(made[0])

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        found = await self._latest(made_by, conversation_id, topic)
        return None if found is None else found[1]

    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        found = await self._latest(made_by, conversation_id, topic)
        if found is None:
            raise ProposalRefused("none")
        proposal_id, proposal = found
        why = refusal(proposal, turn_id, datetime.now(UTC), ttl_s)
        if why is not None:
            raise ProposalRefused(why)
        if await self._one("DELETE FROM proposals WHERE id = %s RETURNING id", (proposal_id,)) is None:
            raise ProposalRefused("none")
        return proposal

    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        return await self._by_id(proposal_id, topic)

    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        proposal = await self._by_id(proposal_id, topic)
        if proposal is None:
            raise ProposalRefused("none")
        if proposal.made_by != made_by:
            raise ProposalRefused("not_yours")
        why = refusal(proposal, turn_id, datetime.now(UTC), ttl_s)
        if why is not None:
            raise ProposalRefused(why)
        if await self._one("DELETE FROM proposals WHERE id = %s RETURNING id", (proposal_id,)) is None:
            raise ProposalRefused("none")
        return proposal

    async def _by_id[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        row = await self._one("SELECT id, household_id, made_by, conversation_id, turn_id, created_at, payload FROM proposals "
                              "WHERE id = %s AND topic = %s", (proposal_id, topic.name))
        return None if row is None else _read(row, topic)

    async def _latest[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> tuple[int, Proposal[P]] | None:
        row = await self._one("SELECT id, household_id, made_by, conversation_id, turn_id, created_at, payload FROM proposals "
                              "WHERE made_by = %s AND (%s OR conversation_id = %s) AND topic = %s ORDER BY id DESC LIMIT 1",
                              (made_by, topic.scope == "person", conversation_id, topic.name))
        return None if row is None else (int(row[0]), _read(row, topic))

    async def _one(self, query: LiteralString, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        try:
            async with self._database.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchone() if cur.description is not None else None
        except (DatabaseUnavailable, psycopg.Error) as e:
            raise ProposalsUnavailable("database unavailable") from e


def _read[P: Payload](row: tuple[Any, ...], topic: Topic[P]) -> Proposal[P]:
    return Proposal(int(row[1]), int(row[2]), int(row[3]), int(row[4]), row[5], topic.decode(row[6]), int(row[0]))
