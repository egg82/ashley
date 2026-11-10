"""The Null Object, live, get and disarm."""

import pytest
from ashley import services
from ashley.watches.watches import Watches, WatchesUnavailable
from watches_blind_support import (FAIL_AFTER, KIND, World, baseline, failed, in_hours, make_arm, quiet, row, run,
                                   scenario, settle_wakes, version_of, wakes_of, wfield, wid)


def test_unregistered_watches_is_a_null_that_raises_unavailable(db_url: str) -> None:
    store = services.get(Watches)

    async def every_call() -> None:
        w = World(db_url, store, 1, 1, 2, 3, 4)
        for call in (store.arm(make_arm(w)), store.disarm(1, 1, KIND, "s1"), store.live(1, 1), store.get(1),
                     store.due(5), store.record(1, 0, baseline({})), store.expire(60)):
            with pytest.raises(WatchesUnavailable):
                await call

    run(every_call())


def test_live_gives_armed_and_paused_soonest_expiry_first(db_url: str) -> None:
    async def body(w: World) -> None:
        late = await w.arm("late", expires_at=in_hours(30))
        soon = await w.arm("soon", expires_at=in_hours(2))
        mid = await w.arm("mid", expires_at=in_hours(10))
        for _ in range(FAIL_AFTER):
            assert await w.store.record(mid, version_of(w.url, mid), failed())
        got = await w.store.live(w.hid, w.owner)
        assert [wid(x) for x in got] == [soon, mid, late]
        assert [wfield(x, "state") for x in got] == ["armed", "paused", "armed"]

    scenario(db_url, body)


def test_live_leaves_out_ended_watches(db_url: str) -> None:
    async def body(w: World) -> None:
        keep = await w.arm("keep")
        await w.arm("gone")
        await w.store.disarm(w.hid, w.owner, KIND, "gone")
        done = await w.arm("done")
        assert await w.store.record(done, version_of(w.url, done), quiet(ends=True))
        assert [wid(x) for x in await w.store.live(w.hid, w.owner)] == [keep]

    scenario(db_url, body)


def test_live_is_that_persons_alone(db_url: str) -> None:
    async def body(w: World) -> None:
        mine = await w.arm("a")
        theirs = await w.arm("a", who=w.mate)
        assert [wid(x) for x in await w.store.live(w.hid, w.owner)] == [mine]
        assert [wid(x) for x in await w.store.live(w.hid, w.mate)] == [theirs]
        assert await w.store.live(w.other_hid, w.stranger) == ()

    scenario(db_url, body)


def test_live_with_nothing_armed_is_empty(db_url: str) -> None:
    async def body(w: World) -> None:
        assert await w.store.live(w.hid, w.owner) == ()

    scenario(db_url, body)


def test_get_finds_a_watch_in_any_state(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        e = await w.arm("e")
        await w.store.disarm(w.hid, w.owner, KIND, "e")
        got = await w.store.get(a)
        assert got is not None and wid(got) == a and wfield(got, "state") == "armed"
        ended = await w.store.get(e)
        assert ended is not None and wfield(ended, "state") == "ended" and wfield(ended, "reason") == "disarmed"

    scenario(db_url, body)


def test_get_carries_the_stored_fields(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a", items={"a": {"seq": 4}})
        got = await w.store.get(a)
        assert got is not None
        assert (wfield(got, "target"), wfield(got, "kind"), wfield(got, "version"), wfield(got, "series")) == \
            ("a", KIND, 0, 0)
        assert wfield(got, "person_id") == w.owner and wfield(got, "household_id") == w.hid

    scenario(db_url, body)


def test_get_of_an_unknown_watch_is_none(db_url: str) -> None:
    async def body(w: World) -> None:
        assert await w.store.get(987654) is None

    scenario(db_url, body)


def test_disarm_ends_the_live_watch_as_disarmed(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        assert await w.store.disarm(w.hid, w.owner, KIND, "a") is True
        r = row(w.url, a)
        assert (r["state"], r["reason"]) == ("ended", "disarmed") and r["ended_at"] is not None

    scenario(db_url, body)


def test_disarm_of_nothing_is_false_and_changes_nothing(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        before = row(w.url, a)
        assert await w.store.disarm(w.hid, w.owner, KIND, "other") is False
        assert await w.store.disarm(w.hid, w.mate, KIND, "a") is False
        assert await w.store.disarm(w.hid, w.owner, "calendar", "a") is False
        assert await w.store.disarm(w.other_hid, w.stranger, KIND, "a") is False
        assert row(w.url, a) == before

    scenario(db_url, body)


def test_disarm_twice_is_true_then_false_and_keeps_the_first_end(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        assert await w.store.disarm(w.hid, w.owner, KIND, "a") is True
        first = row(w.url, a)
        assert await w.store.disarm(w.hid, w.owner, KIND, "a") is False
        assert row(w.url, a) == first

    scenario(db_url, body)


def test_disarm_ends_a_paused_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, 0, failed())
        assert await w.store.disarm(w.hid, w.owner, KIND, "a") is True
        assert row(w.url, a)["reason"] == "disarmed"

    scenario(db_url, body)


def test_disarm_leaves_the_other_persons_watch_and_a_waiting_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        mine = await w.woken("a")
        theirs = await w.arm("a", who=w.mate)
        assert await w.store.disarm(w.hid, w.owner, KIND, "a")
        assert row(w.url, theirs)["state"] == "armed"
        assert len(wakes_of(w.url, mine)) == 1 and wakes_of(w.url, mine)[0]["settled_at"] is None
        settle_wakes(w.url, mine)

    scenario(db_url, body)
