"""InFlight over Postgres, blind: one claimant at a time, an unrenewed claim is orphaned, save and renew keep a claim,
and a lost claim can write nothing."""

import asyncio

import pytest
from ashley.conversations.inflight import Claim, ClaimLost, InFlightUnavailable
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres_inflight import PostgresInFlight
from ashley.db.pool import PoolDatabase
from contract.contract_support import unreachable_conninfo
from contract.conversations_support import POLICY, aexecute, ascalar, holding, run
from ifb_support import CLAIM_S, rig


def test_claim_s_is_what_it_was_built_with(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url, claim_s=7.5) as r:
            assert r.inflight.claim_s == 7.5

    run(go())


def test_begin_names_the_turn_and_conversation(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, said_id = await r.said()
            claim = await r.inflight.begin(conv_id, said_id, "cp0")
            assert (claim.conversation_id, claim.said_id) == (conv_id, said_id)
            assert claim.holder

    run(go())


def test_two_pieces_of_work_have_different_holders(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            a, b = await r.begin(thread="a"), await r.begin(thread="b")
            assert a.holder != b.holder

    run(go())


def test_begin_twice_for_one_turn_is_a_value_error_and_keeps_the_first(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, said_id = await r.said()
            first = await r.inflight.begin(conv_id, said_id, "first")
            with pytest.raises(ValueError):
                await r.inflight.begin(conv_id, said_id, "second")
            await r.expire(first)
            assert [o.checkpoint for o in await r.inflight.orphaned(10)] == ["first"]
            assert await r.rows() == 1

    run(go())


def test_begin_for_a_conversation_that_does_not_exist_is_a_value_error(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            conv_id, said_id = await r.said()
            with pytest.raises(ValueError):
                await r.inflight.begin(conv_id + 1000, said_id, "cp")
            assert await r.rows() == 0

    run(go())


def test_a_fresh_claim_is_not_orphaned(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            await r.begin()
            assert await r.inflight.orphaned(10) == []

    run(go())


def test_an_expired_claim_is_orphaned_with_its_last_checkpoint(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin("cp0")
            await r.inflight.save(claim, "cp1")
            await r.inflight.save(claim, "cp2")
            await r.expire(claim)
            [orphan] = await r.inflight.orphaned(10)
            assert orphan.checkpoint == "cp2"
            assert (orphan.claim.said_id, orphan.claim.conversation_id) == (claim.said_id, claim.conversation_id)
            assert orphan.claim.holder != claim.holder
            assert orphan.attempts == 2

    run(go())


def test_an_orphan_has_its_age_in_seconds_since_the_persons_turn(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.age(claim, 500)
            await r.expire(claim)
            [orphan] = await r.inflight.orphaned(10)
            assert 500 <= orphan.age_s < 560

    run(go())


def test_a_claimed_orphan_is_not_orphaned_again_until_its_new_claim_runs_out(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.expire(claim)
            [first] = await r.inflight.orphaned(10)
            assert await r.inflight.orphaned(10) == []
            await r.expire(first.claim)
            [second] = await r.inflight.orphaned(10)
            assert second.attempts == 3
            assert second.claim.holder not in {claim.holder, first.claim.holder}

    run(go())


def test_attempts_count_every_runner(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            seen: list[int] = []
            for _ in range(4):
                await r.expire(claim)
                [o] = await r.inflight.orphaned(10)
                claim = o.claim
                seen.append(o.attempts)
            assert seen == [2, 3, 4, 5]

    run(go())


def test_orphaned_takes_at_most_limit_oldest_first_and_leaves_the_rest(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claims = [await r.begin(f"cp{i}", thread=f"t{i}") for i in range(5)]
            for i, claim in enumerate(claims):     # begun and lapsed in order, so "oldest" is cp0 on any reading
                await r.age(claim, (5 - i) * 100)
                await r.lapse(claim, (5 - i) * 100)
            first = await r.inflight.orphaned(2)
            assert [o.checkpoint for o in first] == ["cp0", "cp1"]
            rest = await r.inflight.orphaned(10)
            assert [o.checkpoint for o in rest] == ["cp2", "cp3", "cp4"]
            assert await r.inflight.orphaned(10) == []

    run(go())


def test_orphaned_with_a_limit_of_zero_claims_nothing(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.expire(claim)
            assert await r.inflight.orphaned(0) == []
            assert len(await r.inflight.orphaned(5)) == 1

    run(go())


def test_two_callers_at_once_never_claim_the_same_piece(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            for i in range(12):
                await r.begin(f"cp{i}", thread=f"t{i}")
            await r.expire_all()
            batches = await asyncio.gather(*(r.inflight.orphaned(5) for _ in range(4)))
            taken = [o.checkpoint for batch in batches for o in batch]
            assert len(taken) == 12 and len(set(taken)) == 12
            assert all(len(b) <= 5 for b in batches)

    run(go())


def test_only_the_expired_work_is_orphaned(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            stale, live = await r.begin("stale", thread="a"), await r.begin("live", thread="b")
            await r.expire(stale)
            assert [o.checkpoint for o in await r.inflight.orphaned(10)] == ["stale"]
            await r.inflight.renew(live)
            assert await r.rows() == 2

    run(go())


def test_the_old_runner_has_lost_the_claim_for_every_write(db_url: str) -> None:

    async def go() -> None:
        async with rig(db_url) as r:
            old = await r.begin("mine")
            await r.expire(old)
            [taken] = await r.inflight.orphaned(10)
            with pytest.raises(ClaimLost):
                await r.inflight.save(old, "stale write")
            with pytest.raises(ClaimLost):
                await r.inflight.renew(old)
            with pytest.raises(ClaimLost):
                await r.inflight.finish(old, NewTurn("ashley", "stale reply"))
            assert await r.hers() == []
            await r.expire(taken.claim)
            [again] = await r.inflight.orphaned(10)
            assert again.checkpoint == "mine"

    run(go())


def test_the_new_runner_can_save_renew_and_finish(db_url: str) -> None:

    async def go() -> None:
        async with rig(db_url) as r:
            old = await r.begin()
            await r.expire(old)
            [taken] = await r.inflight.orphaned(10)
            await r.inflight.save(taken.claim, "new")
            await r.inflight.renew(taken.claim)
            await r.inflight.finish(taken.claim, NewTurn("ashley", "ok"))
            assert await r.hers() == ["ok"]

    run(go())


def test_save_replaces_the_checkpoint(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin("a")
            await r.inflight.save(claim, "b")
            await r.expire(claim)
            [o] = await r.inflight.orphaned(10)
            assert o.checkpoint == "b"

    run(go())


def test_the_checkpoint_comes_back_byte_for_byte(db_url: str) -> None:
    text = '{"k": "v\\u00e9 \\n  "}\n\tünï \U0001f600 ' + "x" * 50_000

    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin(text)
            await r.expire(claim)
            [o] = await r.inflight.orphaned(10)
            assert o.checkpoint == text

    run(go())


@pytest.mark.parametrize("renewing", ["save", "renew"])
def test_save_and_renew_push_the_claim_out_by_claim_s(db_url: str, renewing: str) -> None:

    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await aexecute(db_url, "UPDATE turn_work SET claimed_until = clock_timestamp() + interval '2 seconds'")
            if renewing == "save":
                await r.inflight.save(claim, "cp1")
            else:
                await r.inflight.renew(claim)
            left = await ascalar(db_url, "SELECT extract(epoch FROM claimed_until - clock_timestamp()) FROM turn_work")
            assert CLAIM_S - 5 < float(left) <= CLAIM_S

    run(go())


def test_a_renewed_claim_is_not_orphaned_while_the_unrenewed_one_is(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            kept, lapsed = await r.begin("kept", thread="a"), await r.begin("lapsed", thread="b")
            await r.expire_all()
            await r.inflight.renew(kept)
            assert [o.checkpoint for o in await r.inflight.orphaned(10)] == ["lapsed"]
            del lapsed

    run(go())


def test_work_of_other_conversations_is_untouched_by_save_and_drop(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            a, b = await r.begin("a", thread="a"), await r.begin("b", thread="b")
            await r.inflight.save(a, "a2")
            await r.inflight.drop(a)
            await r.expire_all()
            assert [o.checkpoint for o in await r.inflight.orphaned(10)] == ["b"]
            del b

    run(go())


def test_save_renew_on_dropped_work_are_claim_lost(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            claim = await r.begin()
            await r.inflight.drop(claim)
            with pytest.raises(ClaimLost):
                await r.inflight.save(claim, "x")
            with pytest.raises(ClaimLost):
                await r.inflight.renew(claim)
            assert await r.rows() == 0

    run(go())


def test_a_lost_save_writes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with rig(db_url) as r:
            old = await r.begin("kept")
            await r.expire(old)
            [taken] = await r.inflight.orphaned(10)
            with pytest.raises(ClaimLost):
                await r.inflight.save(old, "overwritten")
            await r.expire(taken.claim)
            [again] = await r.inflight.orphaned(10)
            assert again.checkpoint == "kept"

    run(go())


@pytest.mark.parametrize("call", ["begin", "save", "renew", "finish", "drop", "orphaned"])
def test_an_unreachable_database_is_unavailable(call: str) -> None:

    async def go() -> None:
        db = PoolDatabase(unreachable_conninfo(), connect_timeout_s=0.1)
        await db.open()
        try:
            inflight = PostgresInFlight(db, POLICY, 15.0)
            claim = Claim(1, 1, "h")
            calls = {"begin": inflight.begin(1, 1, "cp"), "save": inflight.save(claim, "cp"),
                     "renew": inflight.renew(claim), "finish": inflight.finish(claim, NewTurn("ashley", "x")),
                     "drop": inflight.drop(claim), "orphaned": inflight.orphaned(3)}
            for name, coro in calls.items():
                if name != call:
                    coro.close()
            with pytest.raises(InFlightUnavailable):
                await calls[call]
        finally:
            await db.close()

    run(go())


def test_orphaned_skips_work_another_caller_is_in_the_middle_of_claiming(db_url: str) -> None:

    async def go() -> None:
        async with rig(db_url) as r:
            busy, free = await r.begin("busy", thread="a"), await r.begin("free", thread="b")
            await r.expire_all()
            async with holding(db_url, "SELECT 1 FROM turn_work WHERE said_id = %s FOR UPDATE", (busy.said_id,)):
                got = await asyncio.wait_for(r.inflight.orphaned(10), 3)
            assert [o.checkpoint for o in got] == ["free"]
            assert [o.checkpoint for o in await r.inflight.orphaned(10)] == ["busy"]
            del free

    run(go())

