"""claim: the oldest due errand of an answering source, young enough, taken by one job only."""

import asyncio

from contract.conversations_support import gather_settled, holding
from errands_blind_support import HOUSE, SEARCH, World, age_created, attempts_of, claim, row, scenario, seconds_since


def test_claim_takes_the_errand_and_sets_it_running(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        assert await claim(w.errands, (HOUSE,)) == eid
        r = row(w.url, eid)
        assert r["state"] == "running"
        assert r["attempts"] == 1
        assert r["claimed_at"] is not None
        assert 0 <= seconds_since(w.url, eid, "claimed_at") < 30

    scenario(db_url, body)


def test_claim_with_nothing_due_answers_none(db_url: str) -> None:
    async def body(w: World) -> None:
        assert await claim(w.errands, (HOUSE,)) is None

    scenario(db_url, body)


def test_claim_takes_the_oldest_by_creation_not_by_id(db_url: str) -> None:
    async def body(w: World) -> None:
        first = await w.owe()
        second = await w.owe()
        third = await w.owe()
        age_created(w.url, third, 5_000)
        age_created(w.url, second, 2_000)
        assert await claim(w.errands, (HOUSE,)) == third
        assert await claim(w.errands, (HOUSE,)) == second
        assert await claim(w.errands, (HOUSE,)) == first
        assert await claim(w.errands, (HOUSE,)) is None

    scenario(db_url, body)


def test_claim_takes_only_a_source_that_answers(db_url: str) -> None:
    async def body(w: World) -> None:
        searching = await w.owe(SEARCH)
        housing = await w.owe(HOUSE)
        age_created(w.url, searching, 9_000)
        assert await claim(w.errands, (HOUSE,)) == housing
        assert await claim(w.errands, (HOUSE,)) is None
        assert row(w.url, searching)["state"] == "due"
        assert await claim(w.errands, (HOUSE, SEARCH)) == searching

    scenario(db_url, body)


def test_claim_with_no_source_answering_takes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        assert await claim(w.errands, ()) is None
        assert row(w.url, eid)["state"] == "due"
        assert attempts_of(w.url, eid) == 0

    scenario(db_url, body)


def test_claim_skips_an_errand_older_than_max_age(db_url: str) -> None:
    async def body(w: World) -> None:
        stale = await w.owe()
        fresh = await w.owe()
        age_created(w.url, stale, 700)
        age_created(w.url, fresh, 100)
        assert await claim(w.errands, (HOUSE,), max_age_s=600) == fresh
        assert await claim(w.errands, (HOUSE,), max_age_s=600) is None
        r = row(w.url, stale)
        assert r["state"] == "due" and r["attempts"] == 0

    scenario(db_url, body)


def test_claim_takes_nothing_that_is_not_due(db_url: str) -> None:
    async def body(w: World) -> None:
        running, _ = await w.owed_claimed()
        finished, finished_attempt = await w.owed_claimed()
        await w.errands.finish(finished, finished_attempt, "done it")
        refused, refused_attempt = await w.owed_claimed()
        await w.errands.give_up(refused, refused_attempt, "refused")
        assert await claim(w.errands, (HOUSE,)) is None
        assert [row(w.url, e)["state"] for e in (running, finished, refused)] == ["running", "done", "given_up"]

    scenario(db_url, body)


def test_claim_again_after_release_counts_a_second_attempt(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.release(eid, attempt, 5)
        assert await claim(w.errands, (HOUSE,)) == eid
        assert attempts_of(w.url, eid) == 2

    scenario(db_url, body)


def test_a_claim_skips_an_errand_another_job_has_locked(db_url: str) -> None:
    """SKIP LOCKED: the oldest errand is held by someone else's open transaction, so the claim takes the next rather
    than waiting on it or answering none."""

    async def body(w: World) -> None:
        held = await w.owe()
        next_ = await w.owe()
        age_created(w.url, held, 1_000)
        async with holding(w.url, "SELECT id FROM errands WHERE id = %s FOR UPDATE", (held,)):
            got = await asyncio.wait_for(claim(w.errands, (HOUSE,)), 5)
            assert got == next_
        assert row(w.url, held)["state"] == "due"

    scenario(db_url, body)


def test_a_locked_only_errand_is_not_claimed(db_url: str) -> None:
    async def body(w: World) -> None:
        held = await w.owe()
        async with holding(w.url, "SELECT id FROM errands WHERE id = %s FOR UPDATE", (held,)):
            assert await asyncio.wait_for(claim(w.errands, (HOUSE,)), 5) is None

    scenario(db_url, body)


def test_racing_claims_never_take_one_errand_twice(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = {await w.owe() for _ in range(4)}
        got = await gather_settled(*(claim(w.errands, (HOUSE,)) for _ in range(8)))
        assert all(g is None or isinstance(g, int) for g in got), got
        taken = [g for g in got if g is not None]
        assert sorted(taken) == sorted(ids)
        assert len(set(taken)) == len(taken)

    scenario(db_url, body)


def test_racing_claims_for_one_errand_give_it_to_one(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        got = await gather_settled(*(claim(w.errands, (HOUSE,)) for _ in range(6)))
        assert sorted(g for g in got if g is not None) == [eid]
        assert attempts_of(w.url, eid) == 1

    scenario(db_url, body)


def test_claim_order_follows_creation_whatever_the_ids_run(db_url: str) -> None:
    async def body(w: World) -> None:
        first = await w.owe()
        second = await w.owe()
        third = await w.owe()
        age_created(w.url, second, 5_000)
        age_created(w.url, third, 2_000)
        assert [await claim(w.errands, (HOUSE,)) for _ in range(3)] == [second, third, first]

    scenario(db_url, body)
