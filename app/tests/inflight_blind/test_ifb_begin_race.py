"""InFlight.begin racing a finish: a turn handed in again while its first runner is storing her answer waits for that
transaction and is then refused, rather than beginning a second answer to a turn already answered."""

import asyncio

import pytest
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres_inflight import finished
from contract.conversations_support import POLICY, blocked_backend, holding, run
from ifb_support import CLAIM_S, rig


def test_a_begin_waiting_on_a_finish_that_commits_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            async with holding(db_url, "SELECT 1", ()) as conn:
                await finished(conn, POLICY, claim, NewTurn("ashley", "Done.", answers=claim.said_id), CLAIM_S)
                again = asyncio.create_task(r.inflight.begin(claim.conversation_id, claim.said_id, "cp1"))
                await blocked_backend(db_url)
            with pytest.raises(ValueError):
                await again
            assert await r.rows() == 0 and await r.hers() == ["Done."]

    run(go())
