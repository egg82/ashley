"""release, finish, give_up: each acts only on the attempt that still holds the errand running."""

import pytest
from ashley.errands.model import Reason
from errands_blind_support import HOUSE, World, claim, row, scenario, seconds_since, state_name


def test_release_goes_back_to_due_below_the_maximum(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        state = await w.errands.release(eid, attempt, 3)
        assert state_name(state) == "due"
        r = row(w.url, eid)
        assert r["state"] == "due" and r["attempts"] == 1
        assert r["reason"] is None and r["result"] is None

    scenario(db_url, body)


def test_release_at_the_maximum_gives_up_for_attempts(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        state = await w.errands.release(eid, attempt, attempt)
        assert state_name(state) == "given_up"
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "attempts"
        assert r["finished_at"] is not None
        assert await claim(w.errands, (HOUSE,)) is None

    scenario(db_url, body)


def test_release_one_below_the_maximum_still_retries_and_the_next_gives_up(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, first = await w.owed_claimed()
        assert state_name(await w.errands.release(eid, first, 2)) == "due"
        assert await claim(w.errands, (HOUSE,)) == eid
        second = row(w.url, eid)["attempts"]
        assert second == 2
        assert state_name(await w.errands.release(eid, second, 2)) == "given_up"
        assert row(w.url, eid)["reason"] == "attempts"

    scenario(db_url, body)


def test_release_past_the_maximum_also_gives_up(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.release(eid, attempt, 0)
        assert row(w.url, eid)["state"] == "given_up"

    scenario(db_url, body)


def test_release_of_a_stale_attempt_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        before = row(w.url, eid)
        await w.errands.release(eid, attempt + 1, 5)
        await w.errands.release(eid, attempt + 1, 1)
        await w.errands.release(eid, attempt - 1, 5)
        assert row(w.url, eid) == before

    scenario(db_url, body)


def test_release_of_an_errand_no_longer_running_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.finish(eid, attempt, "did it")
        done = row(w.url, eid)
        await w.errands.release(eid, attempt, 5)
        assert row(w.url, eid) == done
        other, other_attempt = await w.owed_claimed()
        await w.errands.release(other, other_attempt, 5)
        due = row(w.url, other)
        await w.errands.release(other, other_attempt, 5)
        assert row(w.url, other) == due

    scenario(db_url, body)


def test_a_released_run_cannot_be_finished_by_its_old_attempt(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.release(eid, attempt, 5)
        assert await claim(w.errands, (HOUSE,)) == eid
        await w.errands.finish(eid, attempt, "late answer from the first run")
        r = row(w.url, eid)
        assert r["state"] == "running" and r["result"] is None

    scenario(db_url, body)


def test_finish_sets_done_with_its_result(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.finish(eid, attempt, "I put cat litter on the list.")
        r = row(w.url, eid)
        assert r["state"] == "done"
        assert r["result"] == "I put cat litter on the list."
        assert r["reason"] is None and r["told_at"] is None
        assert 0 <= seconds_since(w.url, eid, "finished_at") < 30

    scenario(db_url, body)


def test_finish_of_a_stale_attempt_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        before = row(w.url, eid)
        await w.errands.finish(eid, attempt + 1, "wrong run")
        assert row(w.url, eid) == before

    scenario(db_url, body)


def test_finish_of_an_errand_the_sweep_gave_up_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.give_up(eid, attempt, "refused")
        given = row(w.url, eid)
        await w.errands.finish(eid, attempt, "too late")
        assert row(w.url, eid) == given

    scenario(db_url, body)


def test_finish_of_an_errand_not_yet_claimed_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid = await w.owe()
        await w.errands.finish(eid, 0, "never ran")
        await w.errands.finish(eid, 1, "never ran")
        r = row(w.url, eid)
        assert r["state"] == "due" and r["result"] is None

    scenario(db_url, body)


def test_give_up_sets_given_up_with_the_reason(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.give_up(eid, attempt, "refused")
        r = row(w.url, eid)
        assert r["state"] == "given_up" and r["reason"] == "refused"
        assert r["result"] is None
        assert r["finished_at"] is not None
        assert await claim(w.errands, (HOUSE,)) is None

    scenario(db_url, body)


def test_give_up_of_a_stale_attempt_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        before = row(w.url, eid)
        await w.errands.give_up(eid, attempt + 1, "refused")
        assert row(w.url, eid) == before

    scenario(db_url, body)


def test_give_up_of_a_finished_errand_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.finish(eid, attempt, "did it")
        done = row(w.url, eid)
        await w.errands.give_up(eid, attempt, "refused")
        assert row(w.url, eid) == done

    scenario(db_url, body)


@pytest.mark.parametrize("reason", ["attempts", "expired", "interrupted", "refused"])
def test_give_up_stores_whichever_reason_it_is_given(db_url: str, reason: Reason) -> None:
    async def body(w: World) -> None:
        eid, attempt = await w.owed_claimed()
        await w.errands.give_up(eid, attempt, reason)
        assert row(w.url, eid)["reason"] == reason

    scenario(db_url, body)
