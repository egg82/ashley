"""due: live, unexpired watches whose time has come and that have no unsettled wake, longest due first."""

from watches_blind_support import (FAIL_AFTER, KIND, World, defer, failed, lapse, make_due, scenario, settle_wakes,
                                   version_of, wid)


async def due_ids(w: World, limit: int = 50) -> list[int]:
    return [wid(x) for x in await w.store.due(limit)]


def test_due_gives_a_watch_whose_time_has_come(db_url: str) -> None:
    async def body(w: World) -> None:
        a, _ = await w.armed_due("a")
        assert await due_ids(w) == [a]

    scenario(db_url, body)


def test_due_skips_a_watch_not_yet_due(db_url: str) -> None:
    async def body(w: World) -> None:
        a, _ = await w.armed_due("a")
        b, _ = await w.armed_due("b")
        defer(w.url, b, 300)
        assert await due_ids(w) == [a]

    scenario(db_url, body)


def test_due_orders_the_longest_due_first(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = {name: (await w.armed_due(name))[0] for name in ("a", "b", "c", "d")}
        for name, ago in (("a", 100), ("b", 5000), ("c", 700), ("d", 20)):
            make_due(w.url, ids[name], ago)
        assert await due_ids(w) == [ids["b"], ids["c"], ids["a"], ids["d"]]

    scenario(db_url, body)


def test_due_returns_at_most_limit_keeping_the_longest_due(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = [(await w.armed_due(f"t{i}"))[0] for i in range(3)]
        for i, wid_ in enumerate(ids):
            make_due(w.url, wid_, 1000 - i * 100)
        assert await due_ids(w, 2) == ids[:2]
        assert await due_ids(w, 1) == ids[:1]

    scenario(db_url, body)


def test_due_orders_across_people_and_households(db_url: str) -> None:
    async def body(w: World) -> None:
        mine, _ = await w.armed_due("a")
        theirs, _ = await w.armed_due("a", who=w.mate)
        make_due(w.url, mine, 10)
        make_due(w.url, theirs, 900)
        assert await due_ids(w) == [theirs, mine]

    scenario(db_url, body)


def test_due_skips_an_ended_watch(db_url: str) -> None:
    async def body(w: World) -> None:
        a, _ = await w.armed_due("a")
        b, _ = await w.armed_due("b")
        assert await w.store.disarm(w.hid, w.owner, KIND, "b")
        make_due(w.url, b)
        assert await due_ids(w) == [a]

    scenario(db_url, body)


def test_due_skips_a_watch_past_its_expiry(db_url: str) -> None:
    async def body(w: World) -> None:
        a, _ = await w.armed_due("a")
        b, _ = await w.armed_due("b")
        lapse(w.url, b)
        make_due(w.url, b)
        assert await due_ids(w) == [a]

    scenario(db_url, body)


def test_due_skips_a_watch_with_an_unsettled_wake_until_it_is_settled(db_url: str) -> None:
    async def body(w: World) -> None:
        woken = await w.woken("a")
        other, _ = await w.armed_due("b")
        make_due(w.url, woken)
        assert await due_ids(w) == [other]
        settle_wakes(w.url, woken)
        assert sorted(await due_ids(w)) == sorted([woken, other])

    scenario(db_url, body)


def test_the_unsettled_wake_that_holds_a_watch_is_its_own_only(db_url: str) -> None:
    async def body(w: World) -> None:
        woken = await w.woken("a")
        free, _ = await w.armed_due("a", who=w.mate)
        make_due(w.url, woken)
        assert free in await due_ids(w) and woken not in await due_ids(w)

    scenario(db_url, body)


def test_due_skips_a_paused_watch_while_its_paused_wake_waits(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due("a")
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed())
        make_due(w.url, a)
        assert await due_ids(w) == []
        settle_wakes(w.url, a)
        assert await due_ids(w) == [a]

    scenario(db_url, body)


def test_due_gives_a_paused_watch_once_its_retry_has_come(db_url: str) -> None:
    async def body(w: World) -> None:
        a, version = await w.armed_due("a")
        for _ in range(FAIL_AFTER):
            assert await w.store.record(a, version, failed())
        settle_wakes(w.url, a)
        assert await due_ids(w) == []
        make_due(w.url, a)
        assert await due_ids(w) == [a]
        assert version_of(w.url, a) == version

    scenario(db_url, body)


def test_due_with_nothing_armed_is_empty(db_url: str) -> None:
    async def body(w: World) -> None:
        assert await w.store.due(10) == ()

    scenario(db_url, body)
