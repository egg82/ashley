"""Voices in Postgres (`PostgresVoices`) and `NullVoices`: the prints a household's people have, and which devices are
armed to enrol someone. Written from the `Voices` interface alone, so it observes state only through the interface."""

import asyncio
import itertools
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from ashley.channels.voice.voices import Enrolled, NullVoices, PersonPrints, UnknownEnrolee, Voices, VoicesUnavailable
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.inference.voiceprint import Voiceprint
from contract.conversations_support import db_now, db_url as db_url, household, migrated_template as migrated_template
from contract.conversations_support import person, run
from voice_support import satellite_row

MODEL = "titanet-small"
OTHER_MODEL = "other-model"
HOUR = timedelta(hours=1)
HOSTS = itertools.count()


def print_of(*vector: float, model: str = MODEL) -> Voiceprint:
    return Voiceprint(vector=tuple(vector), model=model, audio_ms=1500)


def make(database: Database) -> Voices:
    from ashley.channels.voice.postgres_voices import PostgresVoices  # absent until the implementation lands

    return PostgresVoices(database)


@asynccontextmanager
async def voices(url: str) -> AsyncGenerator[Voices]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield make(database)
    finally:
        await database.close()


def device(url: str, household_id: int, name: str = "office echo") -> int:
    n = next(HOSTS)
    return satellite_row(url, household_id, host=f"10.0.{n // 200}.{n % 200 + 1}", name=name).device.id


def soon(url: str) -> datetime:
    return db_now(url) + HOUR


def test_prints_are_one_household_one_model_ordered_by_person_id(db_url: str) -> None:
    mine, theirs = household(db_url, "mine"), household(db_url, "theirs")
    third, first, second = (person(db_url, mine, n) for n in ("c", "a", "b"))
    outsider = person(db_url, theirs, "z")
    here, there = device(db_url, mine, "here"), device(db_url, theirs, "there")

    async def scenario() -> None:
        async with voices(db_url) as v:
            for who, where, vec, model in ((third, here, (0.0, 1.0), MODEL), (first, here, (1.0, 0.0), MODEL),
                                           (second, here, (0.5, 0.25), MODEL), (second, here, (0.25, 0.5), OTHER_MODEL),
                                           (outsider, there, (0.5, 0.5), MODEL)):
                await v.arm(where, who, 1, soon(db_url))
                assert await v.enrol(where, print_of(*vec, model=model)) == Enrolled(who, 0)
            got = await v.prints(mine, MODEL)
            assert [p.person_id for p in got] == sorted([first, second, third])
            assert {p.person_id: p.vectors for p in got} == {
                first: ((1.0, 0.0),), second: ((0.5, 0.25),), third: ((0.0, 1.0),)}
            assert await v.prints(mine, OTHER_MODEL) == (PersonPrints(second, ((0.25, 0.5),)),)
            assert await v.prints(theirs, MODEL) == (PersonPrints(outsider, ((0.5, 0.5),)),)

    run(scenario())


def test_nothing_enrolled_is_empty_for_every_household_and_model(db_url: str) -> None:
    home = household(db_url)
    person(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            assert await v.prints(home, MODEL) == ()
            assert await v.prints(home + 1000, MODEL) == ()

    run(scenario())


def test_a_persons_prints_are_oldest_first(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)
    sequence = [(1.0, 0.0), (0.0, 1.0), (0.5, 0.5), (0.25, 0.75)]

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, who, len(sequence), soon(db_url))
            for vec in sequence:
                assert await v.enrol(where, print_of(*vec)) is not None
            assert await v.prints(home, MODEL) == (PersonPrints(who, tuple(sequence)),)

    run(scenario())


def test_enrolling_counts_the_wakes_down_to_zero_then_stops(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, who, 3, soon(db_url))
            assert await v.enrol(where, print_of(1.0, 0.0)) == Enrolled(who, 2)
            assert await v.enrol(where, print_of(0.0, 1.0)) == Enrolled(who, 1)
            assert await v.enrol(where, print_of(0.5, 0.5)) == Enrolled(who, 0)
            assert await v.enrol(where, print_of(0.25, 0.75)) is None
            got = await v.prints(home, MODEL)
            assert got == (PersonPrints(who, ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5))),), "the fourth wake stored nothing"

    run(scenario())


def test_a_device_never_armed_stores_nothing(db_url: str) -> None:
    home = household(db_url)
    person(db_url, home)
    where = device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            assert await v.enrol(where, print_of(1.0, 0.0)) is None
            assert await v.enrol(where + 999, print_of(1.0, 0.0)) is None
            assert await v.prints(home, MODEL) == ()

    run(scenario())


def test_a_device_is_armed_for_itself_and_not_for_its_neighbour(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)
    armed, idle = device(db_url, home, "armed"), device(db_url, home, "idle")

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(armed, who, 2, soon(db_url))
            assert await v.enrol(idle, print_of(1.0, 0.0)) is None
            assert await v.prints(home, MODEL) == ()
            assert await v.enrol(armed, print_of(1.0, 0.0)) == Enrolled(who, 1)

    run(scenario())


def test_an_arming_whose_until_has_passed_enrols_nothing(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, who, 5, db_now(db_url) - timedelta(seconds=30))
            assert await v.enrol(where, print_of(1.0, 0.0)) is None
            assert await v.prints(home, MODEL) == ()

    run(scenario())


def test_an_arming_a_moment_ahead_still_enrols(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, who, 1, db_now(db_url) + timedelta(minutes=5))
            assert await v.enrol(where, print_of(1.0, 0.0)) == Enrolled(who, 0)

    run(scenario())


def test_arming_again_replaces_the_previous_arming(db_url: str) -> None:
    home = household(db_url)
    first, second = person(db_url, home, "first"), person(db_url, home, "second")
    where = device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, first, 5, soon(db_url))
            await v.arm(where, second, 1, soon(db_url))
            assert await v.enrol(where, print_of(1.0, 0.0)) == Enrolled(second, 0)
            assert await v.enrol(where, print_of(0.0, 1.0)) is None, "the first arming's wakes did not survive"
            assert await v.prints(home, MODEL) == (PersonPrints(second, ((1.0, 0.0),)),)

    run(scenario())


def test_arming_again_for_the_same_person_resets_the_wakes(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, who, 2, soon(db_url))
            assert await v.enrol(where, print_of(1.0, 0.0)) == Enrolled(who, 1)
            await v.arm(where, who, 4, soon(db_url))
            assert await v.enrol(where, print_of(0.0, 1.0)) == Enrolled(who, 3)

    run(scenario())


def test_a_second_arming_with_a_passed_until_disarms_the_device(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, who, 3, soon(db_url))
            await v.arm(where, who, 3, db_now(db_url) - timedelta(seconds=30))
            assert await v.enrol(where, print_of(1.0, 0.0)) is None

    run(scenario())


@pytest.mark.parametrize("wakes", [0, -1, -100])
def test_arming_for_under_one_wake_raises_and_leaves_the_old_arming(db_url: str, wakes: int) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(where, who, 2, soon(db_url))
            with pytest.raises(ValueError):
                await v.arm(where, who, wakes, soon(db_url))
            assert await v.enrol(where, print_of(1.0, 0.0)) == Enrolled(who, 1)

    run(scenario())


def test_arming_a_person_of_another_household_is_unknown(db_url: str) -> None:
    mine, theirs = household(db_url, "mine"), household(db_url, "theirs")
    outsider = person(db_url, theirs)
    where = device(db_url, mine)

    async def scenario() -> None:
        async with voices(db_url) as v:
            with pytest.raises(UnknownEnrolee):
                await v.arm(where, outsider, 1, soon(db_url))
            assert await v.enrol(where, print_of(1.0, 0.0)) is None
            assert await v.prints(theirs, MODEL) == ()

    run(scenario())


def test_arming_an_unknown_person_or_device_is_unknown(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            with pytest.raises(UnknownEnrolee):
                await v.arm(where, who + 1000, 1, soon(db_url))
            with pytest.raises(UnknownEnrolee):
                await v.arm(where + 1000, who, 1, soon(db_url))

    run(scenario())


def test_two_wakes_cannot_both_take_the_last_one(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)
    devices = [device(db_url, home, f"echo {i}") for i in range(6)]

    async def scenario() -> None:
        async with voices(db_url) as one, voices(db_url) as other:
            for where in devices:
                await one.arm(where, who, 1, soon(db_url))
            calls = [(one if i % 2 else other).enrol(where, print_of(1.0, 0.0))
                     for where in devices for i in range(2)]
            results = await asyncio.gather(*calls)
            for k in range(len(devices)):
                pair = results[2 * k:2 * k + 2]
                assert sorted(r is None for r in pair) == [False, True], pair
                assert [r for r in pair if r is not None] == [Enrolled(who, 0)]
            (stored,) = await one.prints(home, MODEL)
            assert len(stored.vectors) == len(devices), "one print per device, not per racing wake"

    run(scenario())


def test_many_wakes_racing_for_a_few_take_exactly_the_few(db_url: str) -> None:
    home = household(db_url)
    who, where = person(db_url, home), device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as one, voices(db_url) as other:
            await one.arm(where, who, 3, soon(db_url))
            results = await asyncio.gather(*[(one if i % 2 else other).enrol(where, print_of(1.0, 0.0))
                                             for i in range(8)])
            taken = [r for r in results if r is not None]
            assert sorted(r.remaining for r in taken) == [0, 1, 2]
            (stored,) = await one.prints(home, MODEL)
            assert len(stored.vectors) == 3

    run(scenario())


def test_forget_counts_the_prints_it_deleted_and_leaves_other_people(db_url: str) -> None:
    home = household(db_url)
    gone, kept = person(db_url, home, "gone"), person(db_url, home, "kept")
    where = device(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            for who, vec, model in ((gone, (1.0, 0.0), MODEL), (kept, (0.0, 1.0), MODEL), (gone, (0.5, 0.5), MODEL),
                                    (gone, (0.25, 0.75), OTHER_MODEL), (kept, (0.75, 0.25), MODEL)):
                await v.arm(where, who, 1, soon(db_url))
                assert await v.enrol(where, print_of(*vec, model=model)) is not None
            assert await v.forget(gone) == 3, "every print, whatever its model"
            assert await v.prints(home, MODEL) == (PersonPrints(kept, ((0.0, 1.0), (0.75, 0.25))),)
            assert await v.prints(home, OTHER_MODEL) == ()
            assert await v.forget(gone) == 0

    run(scenario())


def test_forgetting_someone_with_no_prints_deletes_nothing(db_url: str) -> None:
    home = household(db_url)
    who = person(db_url, home)

    async def scenario() -> None:
        async with voices(db_url) as v:
            assert await v.forget(who) == 0
            assert await v.forget(who + 1000) == 0

    run(scenario())


def test_forget_removes_the_arming_for_that_person_only(db_url: str) -> None:
    home = household(db_url)
    gone, kept = person(db_url, home, "gone"), person(db_url, home, "kept")
    armed_gone, armed_kept = device(db_url, home, "one"), device(db_url, home, "two")

    async def scenario() -> None:
        async with voices(db_url) as v:
            await v.arm(armed_gone, gone, 3, soon(db_url))
            await v.arm(armed_kept, kept, 3, soon(db_url))
            assert await v.forget(gone) == 0
            assert await v.enrol(armed_gone, print_of(1.0, 0.0)) is None
            assert await v.enrol(armed_kept, print_of(0.0, 1.0)) == Enrolled(kept, 2)
            assert await v.prints(home, MODEL) == (PersonPrints(kept, ((0.0, 1.0),)),)

    run(scenario())


def test_an_unreachable_database_is_voices_unavailable() -> None:
    async def scenario() -> None:
        database = PoolDatabase("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1", connect_timeout_s=0.1)
        await database.open()
        try:
            v = make(database)
            with pytest.raises(VoicesUnavailable):
                await v.prints(1, MODEL)
            with pytest.raises(VoicesUnavailable):
                await v.enrol(1, print_of(1.0, 0.0))
            with pytest.raises(VoicesUnavailable):
                await v.forget(1)
            with pytest.raises(VoicesUnavailable):
                await v.arm(1, 1, 1, datetime.now())
        finally:
            await database.close()

    run(scenario())


def test_null_voices_know_nobody_and_store_nothing() -> None:
    async def scenario() -> None:
        null = Voices.null()
        assert isinstance(null, NullVoices)
        assert await null.prints(1, MODEL) == ()
        assert await null.enrol(1, print_of(1.0, 0.0)) is None

    run(scenario())


def test_null_voices_raise_on_the_admin_writes_only() -> None:
    async def scenario() -> None:
        null = NullVoices()
        with pytest.raises(VoicesUnavailable):
            await null.arm(1, 1, 1, datetime.now())
        with pytest.raises(VoicesUnavailable):
            await null.forget(1)

    run(scenario())
