"""`Wakes` on a real database: one wake per (household, event id), oldest-first due, settled once, pruned only when
settled and past the limit, nothing of a wake in a log, Null and unreachable databases raising."""

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from ashley.db.pool import PoolDatabase
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import NullWakes, Outcome, Received, Wake, Wakes, WakesUnavailable
from contract.conversations_support import household, run
from wb_support import NOW, add_device, wake


@asynccontextmanager
async def wakes(url: str) -> AsyncGenerator[Wakes]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresWakes(db)
    finally:
        await db.close()


class Home:
    def __init__(self, url: str) -> None:
        self.url = url
        self.one = household(url, "one")
        self.two = household(url, "two")
        self.device = add_device(url, self.one, "tok-one", "ha-one")
        self.other_device = add_device(url, self.two, "tok-two", "ha-two")


@pytest.fixture
def home(db_url: str) -> Home:
    return Home(db_url)


def test_a_new_wake_is_stored_and_due_with_its_fields(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            got = await w.receive(home.device, wake(home.one, "e1", "arrived", "person.alana", "front_door"))
            assert got.new is True
            (due,) = await w.due(10)
            house = due.wake
            assert isinstance(house, Wake)
            assert due.id == got.id and due.age_s >= 0
            assert house.household_id == home.one and house.event_id == "e1" and house.event == "arrived"
            assert (house.who, house.what, house.at) == ("person.alana", "front_door", NOW)

    run(go())


def test_optional_fields_stay_absent(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            await w.receive(home.device, wake(home.one, who=None, what=None))
            (due,) = await w.due(10)
            house = due.wake
            assert isinstance(house, Wake)
            assert (house.who, house.what) == (None, None)

    run(go())


def test_the_same_event_id_again_is_the_same_wake_and_changes_nothing(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            first = await w.receive(home.device, wake(home.one, "e1", "arrived", "person.alana", "a"))
            again = await w.receive(home.device, wake(home.one, "e1", "left", "person.sam", "b"))
            assert again == Received(first.id, False)
            (due,) = await w.due(10)
            house = due.wake
            assert isinstance(house, Wake)
            assert (house.event, house.who, house.what) == ("arrived", "person.alana", "a")

    run(go())


def test_the_same_event_id_from_another_device_of_the_household_is_still_one_wake(home: Home) -> None:
    second = add_device(home.url, home.one, "tok-three", "ha-two")

    async def go() -> None:
        async with wakes(home.url) as w:
            a = await w.receive(home.device, wake(home.one, "e1"))
            b = await w.receive(second, wake(home.one, "e1"))
            assert (a.new, b.new, a.id) == (True, False, b.id)

    run(go())


def test_the_same_event_id_in_another_household_is_its_own_wake(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            a = await w.receive(home.device, wake(home.one, "e1"))
            b = await w.receive(home.other_device, wake(home.two, "e1"))
            assert b.new is True and a.id != b.id
            assert {d.wake.household_id for d in await w.due(10)} == {home.one, home.two}

    run(go())


def test_many_deliveries_racing_store_one_wake(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            got = await asyncio.gather(*(w.receive(home.device, wake(home.one, "race")) for _ in range(12)))
            assert sum(r.new for r in got) == 1 and len({r.id for r in got}) == 1
            assert len(await w.due(50)) == 1

    run(go())


def test_due_is_oldest_first_and_bounded_by_the_limit(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            ids = [(await w.receive(home.device, wake(home.one, f"e{n}"))).id for n in range(5)]
            assert [d.id for d in await w.due(50)] == ids
            assert [d.id for d in await w.due(2)] == ids[:2]
            assert await w.due(0) == ()

    run(go())


def test_age_grows_while_a_wake_waits(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            await w.receive(home.device, wake(home.one))
            (early,) = await w.due(1)
            await asyncio.sleep(0.3)
            (late,) = await w.due(1)
            assert late.age_s >= early.age_s + 0.2

    run(go())


@pytest.mark.parametrize("outcome", ["turn", "failed", "no_rule", "ambiguous", "no_person", "expired"])
def test_a_wake_settles_once_with_any_outcome_and_is_no_longer_due(home: Home, outcome: Outcome) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            got = await w.receive(home.device, wake(home.one))
            assert await w.settle(got.id, outcome) is True
            assert await w.due(10) == ()
            assert await w.settle(got.id, "failed") is False

    run(go())


def test_settling_what_does_not_exist_is_false(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            assert await w.settle(987654, "turn") is False

    run(go())


def test_a_settled_event_id_arriving_again_is_not_a_new_wake_and_is_not_due(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            got = await w.receive(home.device, wake(home.one, "e1"))
            await w.settle(got.id, "turn")
            again = await w.receive(home.device, wake(home.one, "e1"))
            assert again == Received(got.id, False)
            assert await w.due(10) == ()

    run(go())


def test_prune_removes_settled_wakes_past_the_limit_and_nothing_else(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            old = await w.receive(home.device, wake(home.one, "old"))
            waiting = await w.receive(home.device, wake(home.one, "waiting"))
            await w.settle(old.id, "turn")
            await asyncio.sleep(0.4)
            fresh = await w.receive(home.device, wake(home.one, "fresh"))
            await w.settle(fresh.id, "no_rule")
            assert await w.prune(0.2) == 1
            assert (await w.receive(home.device, wake(home.one, "old"))).new is True
            assert (await w.receive(home.device, wake(home.one, "fresh"))).new is False
            assert [d.id for d in await w.due(10)] == [waiting.id, (await w.receive(home.device, wake(home.one, "old"))).id]

    run(go())


def test_prune_never_takes_an_unsettled_wake_however_old(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            got = await w.receive(home.device, wake(home.one))
            await asyncio.sleep(0.3)
            assert await w.prune(0.0) == 0
            assert [d.id for d in await w.due(10)] == [got.id]

    run(go())


def test_prune_keeps_a_settled_wake_inside_the_limit(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            got = await w.receive(home.device, wake(home.one))
            await w.settle(got.id, "turn")
            assert await w.prune(3600) == 0
            assert (await w.receive(home.device, wake(home.one))).new is False

    run(go())


def test_prune_counts_every_wake_it_deletes(home: Home) -> None:
    async def go() -> None:
        async with wakes(home.url) as w:
            for n in range(3):
                await w.settle((await w.receive(home.device, wake(home.one, f"e{n}"))).id, "turn")
            await asyncio.sleep(0.2)
            assert await w.prune(0.1) == 3
            assert await w.prune(0.1) == 0

    run(go())


def test_nothing_of_a_wake_reaches_a_log(home: Home, capsys: pytest.CaptureFixture[str]) -> None:
    from ashley import logs

    logs.setup({"LOG_LEVEL": "debug"})

    async def go() -> None:
        async with wakes(home.url) as w:
            got = await w.receive(home.device, wake(home.one, "PLANTED-EVENTID-zq", "planted_event", "person.plantedwho",
                                                    "plantedwhat"))
            await w.receive(home.device, wake(home.one, "PLANTED-EVENTID-zq"))
            await w.settle(got.id, "turn")
            await asyncio.sleep(0.2)
            await w.prune(0.1)

    run(go())
    out = capsys.readouterr().out + capsys.readouterr().err
    for planted in ("plantedwho", "plantedwhat", "PLANTED-EVENTID-zq"):
        assert planted not in out


def test_an_unwired_process_raises_on_every_call() -> None:
    null = NullWakes()

    async def go() -> None:
        for call in (null.receive(1, wake(1)), null.due(1), null.settle(1, "turn"), null.prune(1.0)):
            with pytest.raises(WakesUnavailable):
                await call

    run(go())


def test_an_unreachable_database_raises_wakes_unavailable() -> None:
    async def go() -> None:
        db = PoolDatabase("postgresql://nobody:x@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.1)
        w = PostgresWakes(db)
        for call in (w.receive(1, wake(1)), w.due(1), w.settle(1, "turn"), w.prune(1.0)):
            with pytest.raises(WakesUnavailable):
                await call

    run(go())


def test_the_clock_is_the_databases_not_the_wakes(home: Home) -> None:
    """A wake that says it happened long ago is still only as old as its arrival."""
    start = time.monotonic()

    async def go() -> None:
        async with wakes(home.url) as w:
            await w.receive(home.device, wake(home.one))
            (due,) = await w.due(1)
            assert due.age_s < (time.monotonic() - start) + 5

    run(go())
