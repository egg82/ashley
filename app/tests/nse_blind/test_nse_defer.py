"""`InFlight.defer`: the claim held for a given time in place of `claim_s`, so the work is resumed no sooner; and the
work in a runner's hands (`channels.inflight`) that uses it."""

from dataclasses import replace

import pytest
from ashley.channels import checkpoint as cp
from ashley.channels.checkpoint import Checkpoint
from ashley.channels.inflight import Saved, Unsaved, begin
from ashley.channels.model import Inbound
from ashley.channels.tool_loop import Progress
from ashley.conversations.inflight import Claim, ClaimLost, InFlight, NullInFlight
from contract.conversations_support import run
from nse_blind_support import Rig, rig

LATER = Inbound(1, "web:1", "hi", "chat", "text", "owner", 1, False, None, "web", later=True, later_by="turn")


async def _begun(r: Rig) -> Claim:
    conv_id, said_id = await r.said()
    return await r.inflight.begin(conv_id, said_id, "cp0")


def test_defer_holds_the_claim_for_the_seconds_given(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url, claim_s=60) as r:
            claim = await _begun(r)
            await r.inflight.defer(claim, 300)
            assert 290 < r.left_s() <= 300.5
            assert await r.inflight.orphaned(10) == []

    run(go())


def test_defer_replaces_claim_s_rather_than_adding_to_it(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url, claim_s=60) as r:
            claim = await _begun(r)
            await r.inflight.defer(claim, 2)
            assert 0 < r.left_s() <= 2.5

    run(go())


def test_a_deferred_piece_is_orphaned_once_its_time_has_run_out_with_its_checkpoint_kept(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await _begun(r)
            await r.inflight.defer(claim, 300)
            await r.expire()
            got = await r.inflight.orphaned(10)
            assert [(o.claim.said_id, o.checkpoint, o.attempts) for o in got] == [(claim.said_id, "cp0", 2)]

    run(go())


def test_defer_raises_claim_lost_when_another_runner_took_the_work(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await _begun(r)
            await r.expire()
            assert len(await r.inflight.orphaned(10)) == 1
            with pytest.raises(ClaimLost):
                await r.inflight.defer(claim, 300)

    run(go())


def test_defer_raises_claim_lost_once_the_work_is_gone(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await _begun(r)
            assert await r.inflight.drop(claim)
            with pytest.raises(ClaimLost):
                await r.inflight.defer(claim, 300)

    run(go())


class Renewals(NullInFlight):
    """The default `defer` is the base class's: it renews."""

    def __init__(self, error: Exception | None = None) -> None:
        self.renewed: list[Claim] = []
        self.error = error

    async def renew(self, claim: Claim) -> None:
        if self.error is not None:
            raise self.error
        self.renewed.append(claim)


def test_the_default_defer_renews_the_claim() -> None:
    inflight: InFlight = Renewals()
    claim = Claim(1, 2, "me")
    run(inflight.defer(claim, 500))
    assert isinstance(inflight, Renewals) and inflight.renewed == [claim]


def test_the_default_defer_raises_what_the_renewal_raises() -> None:
    inflight = Renewals(ClaimLost())

    async def go() -> None:
        with pytest.raises(ClaimLost):
            await inflight.defer(Claim(1, 2, "me"), 5)

    run(go())


def test_the_null_inflight_defers_without_error() -> None:
    run(NullInFlight().defer(Claim(1, 2, ""), 5))


# --- the work in a runner's hands --------------------------------------------------------------------------------


def _checkpoint(conv_id: int, said_id: int) -> Checkpoint:
    return Checkpoint(LATER, conv_id, said_id, 1, {}, Progress((), 0, 0))


def test_saved_work_retries_remembers_the_line_in_its_checkpoint_and_defers_the_claim(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, said_id = await r.said()
            work = await begin(LATER, _checkpoint(conv_id, said_id))
            assert isinstance(work, Saved)
            assert work.retries is True
            assert work.unreachable_told is False
            await work.told_unreachable()
            assert work.unreachable_told is True
            await work.defer(250)
            assert 240 < r.left_s() <= 250.5
            await r.expire()
            [orphan] = await r.inflight.orphaned(5)
            assert cp.loads(orphan.checkpoint).unreachable_told is True

    run(go())


def test_work_that_is_not_saved_does_not_retry_and_has_nothing_to_tell_or_defer() -> None:
    async def go() -> None:
        work = await begin(replace(LATER, later=False), _checkpoint(1, 2))
        assert isinstance(work, Unsaved)
        assert work.retries is False
        assert work.unreachable_told is True
        await work.told_unreachable()
        await work.defer(5)

    run(go())


def test_the_checkpoint_round_trips_the_told_flag() -> None:
    told = replace(_checkpoint(1, 2), unreachable_told=True)
    assert cp.loads(cp.dumps(told)).unreachable_told is True
    assert cp.loads(cp.dumps(_checkpoint(1, 2))).unreachable_told is False


def test_a_checkpoint_saved_before_the_flag_existed_loads_as_not_told() -> None:
    import json
    raw = json.loads(cp.dumps(_checkpoint(1, 2)))
    del raw["unreachable_told"]
    assert cp.loads(json.dumps(raw)).unreachable_told is False


