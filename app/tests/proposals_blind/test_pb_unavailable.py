"""A store whose database cannot be reached raises ProposalsUnavailable from every call, and the schema the migration
leaves is the one proposals table, the two old tables gone."""

import pytest
from ashley.db.pool import PoolDatabase
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import HOUSE
from ashley.senses.proposals import ProposalsUnavailable
from contract.conversations_support import run, scalar
from proposals_blind_support import TTL, house_change, proposal

DEAD = "postgresql://postgres:pg@127.0.0.1:1/postgres"


def test_every_call_raises_proposals_unavailable_when_the_database_is_down() -> None:
    async def go() -> None:
        db = PoolDatabase(DEAD, connect_timeout_s=0.1)
        kept = PostgresProposals(db)
        with pytest.raises(ProposalsUnavailable):
            await kept.propose(proposal(house_change(), 1, 1), TTL)
        with pytest.raises(ProposalsUnavailable):
            await kept.pending(1, 1, HOUSE)
        with pytest.raises(ProposalsUnavailable):
            await kept.take(1, 1, HOUSE, 2, TTL)
        await db.close()

    run(go())


def test_the_migration_leaves_one_proposals_table_and_drops_the_two_it_replaced(db_url: str) -> None:
    present = {t: scalar(db_url, "SELECT to_regclass(%s) IS NOT NULL", (t,)) for t in ("proposals", "deposit_proposals", "house_proposals")}
    assert present == {"proposals": True, "deposit_proposals": False, "house_proposals": False}
