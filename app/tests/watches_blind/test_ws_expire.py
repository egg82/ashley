"""expire: live watches past expires_at end `expired`; ended ones past keep_s with no unsettled wake are deleted."""

from watches_blind_support import (FAIL_AFTER, KEEP_S, KIND, World, age_ended, exists, expired_of, failed, lapse,
                                   pruned_of, quiet, row, scenario, settle_wakes, wakes_of)


def test_expire_ends_a_live_watch_past_its_expiry_as_expired(db_url: str) -> None:
    async def body(w: World) -> None:
        late = await w.arm("late")
        old = await w.arm("old", items={"s1": {"seq": 1}})
        lapse(w.url, old)
        counts = await w.store.expire(KEEP_S)
        assert (expired_of(counts), pruned_of(counts)) == (1, 0)
        r = row(w.url, old)
        assert (r["state"], r["reason"], r["baseline"]) == ("ended", "expired", {"s1": {"seq": 1}})
        assert r["ended_at"] is not None
        assert row(w.url, late)["state"] == "armed"

    scenario(db_url, body)


def test_expire_ends_a_paused_watch_too_and_writes_no_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, 0, failed())
        settle_wakes(w.url, a)
        lapse(w.url, a)
        assert expired_of(await w.store.expire(KEEP_S)) == 1
        assert row(w.url, a)["reason"] == "expired" and len(wakes_of(w.url, a)) == 1

    scenario(db_url, body)


def test_expire_leaves_an_already_ended_watch_with_its_reason(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        assert await w.store.record(a, 0, quiet(ends=True))
        lapse(w.url, a)
        before = row(w.url, a)
        assert expired_of(await w.store.expire(KEEP_S)) == 0
        assert row(w.url, a) == before

    scenario(db_url, body)


def test_expire_with_nothing_to_do_counts_zero(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.arm("a")
        counts = await w.store.expire(KEEP_S)
        assert (expired_of(counts), pruned_of(counts)) == (0, 0)

    scenario(db_url, body)


def test_expire_counts_each_watch_it_ends(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = [await w.arm(f"t{i}") for i in range(3)]
        for i in ids[:2]:
            lapse(w.url, i)
        assert expired_of(await w.store.expire(KEEP_S)) == 2
        assert expired_of(await w.store.expire(KEEP_S)) == 0

    scenario(db_url, body)


def test_expire_deletes_an_ended_watch_older_than_keep_s(db_url: str) -> None:
    async def body(w: World) -> None:
        old = await w.arm("old")
        young = await w.arm("young")
        assert await w.store.disarm(w.hid, w.owner, KIND, "old")
        assert await w.store.disarm(w.hid, w.owner, KIND, "young")
        age_ended(w.url, old, KEEP_S + 100)
        age_ended(w.url, young, KEEP_S - 600)
        counts = await w.store.expire(KEEP_S)
        assert pruned_of(counts) == 1 and expired_of(counts) == 0
        assert not exists(w.url, old) and exists(w.url, young)

    scenario(db_url, body)


def test_expire_keeps_an_old_ended_watch_with_an_unsettled_wake(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.woken("a")
        assert await w.store.disarm(w.hid, w.owner, KIND, "a")
        age_ended(w.url, a, KEEP_S + 100)
        assert pruned_of(await w.store.expire(KEEP_S)) == 0
        assert exists(w.url, a) and len(wakes_of(w.url, a)) == 1

    scenario(db_url, body)


def test_expire_deletes_once_the_wake_is_settled_and_takes_its_wakes_along(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.woken("a")
        assert await w.store.disarm(w.hid, w.owner, KIND, "a")
        age_ended(w.url, a, KEEP_S + 100)
        settle_wakes(w.url, a)
        assert pruned_of(await w.store.expire(KEEP_S)) == 1
        assert not exists(w.url, a) and wakes_of(w.url, a) == []

    scenario(db_url, body)


def test_expire_never_prunes_a_live_watch_however_old(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        age_ended(w.url, a, 10_000)
        assert pruned_of(await w.store.expire(1)) == 0
        assert exists(w.url, a)

    scenario(db_url, body)


def test_a_watch_expired_now_is_not_pruned_in_the_same_call(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        lapse(w.url, a)
        counts = await w.store.expire(KEEP_S)
        assert (expired_of(counts), pruned_of(counts)) == (1, 0) and exists(w.url, a)

    scenario(db_url, body)


def test_a_watch_expired_long_ago_is_ended_then_pruned_by_later_expiry(db_url: str) -> None:
    async def body(w: World) -> None:
        a = await w.arm("a")
        lapse(w.url, a)
        await w.store.expire(KEEP_S)
        age_ended(w.url, a, KEEP_S + 100)
        assert pruned_of(await w.store.expire(KEEP_S)) == 1 and not exists(w.url, a)

    scenario(db_url, body)


def test_pruning_one_watch_leaves_the_others_wakes(db_url: str) -> None:
    async def body(w: World) -> None:
        keep = await w.woken("keep")
        gone = await w.arm("gone")
        assert await w.store.disarm(w.hid, w.owner, KIND, "gone")
        age_ended(w.url, gone, KEEP_S + 100)
        await w.store.expire(KEEP_S)
        assert len(wakes_of(w.url, keep)) == 1 and not exists(w.url, gone)

    scenario(db_url, body)
