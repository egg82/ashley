"""Voices in Postgres: arming a device, a wake taking an enrolment's wakes once each, prints read back per person and
model, forgetting a person, and an unreachable database."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any, TypeVar

import pytest
from ashley.channels.voice.postgres_voices import PostgresVoices
from ashley.channels.voice.voices import Enrolled, UnknownEnrolee, VoicesUnavailable
from ashley.db.database import NullDatabase
from ashley.db.pool import PoolDatabase
from ashley.inference.voiceprint import Voiceprint
from contract.conversations_support import db_now, db_url as db_url, household, person
from contract.conversations_support import migrated_template as migrated_template, scalar
from voice_support import satellite_row

R = TypeVar("R")
PRINT = Voiceprint((0.6, 0.8), "titanet", 1500)


def with_voices(url: str, body: Callable[[PostgresVoices], Awaitable[R]]) -> R:
    async def scenario() -> R:
        database = PoolDatabase(url)
        await database.open()
        try:
            return await body(PostgresVoices(database))
        finally:
            await database.close()

    return asyncio.run(scenario())


def later(url: str, minutes: float = 30) -> datetime:
    return db_now(url) + timedelta(minutes=minutes)


def test_an_armed_device_stores_its_wakes_for_the_person_until_they_run_out(db_url: str) -> None:
    home = household(db_url)
    alana, device = person(db_url, home), satellite_row(db_url, home).device.id

    async def body(voices: PostgresVoices) -> list[Enrolled | None]:
        await voices.arm(device, alana, 2, later(db_url))
        return [await voices.enrol(device, PRINT) for _ in range(3)]

    assert with_voices(db_url, body) == [Enrolled(alana, 1), Enrolled(alana, 0), None]
    assert scalar(db_url, "SELECT count(*) FROM voice_enrolments") == 0, "used up, the row goes"
    assert scalar(db_url, "SELECT count(*) FROM voiceprints WHERE device_id = %s AND person_id = %s",
                  (device, alana)) == 2


def test_two_wakes_racing_for_the_last_one_store_one_print(db_url: str) -> None:
    home = household(db_url)
    alana, device = person(db_url, home), satellite_row(db_url, home).device.id

    async def body(voices: PostgresVoices) -> list[Enrolled | None]:
        await voices.arm(device, alana, 1, later(db_url))
        return list(await asyncio.gather(voices.enrol(device, PRINT), voices.enrol(device, PRINT)))

    assert sorted(with_voices(db_url, body), key=lambda e: e is None) == [Enrolled(alana, 0), None]
    assert scalar(db_url, "SELECT count(*) FROM voiceprints") == 1


def test_an_expired_enrolment_stores_nothing_and_is_deleted(db_url: str) -> None:
    home = household(db_url)
    alana, device = person(db_url, home), satellite_row(db_url, home).device.id

    async def body(voices: PostgresVoices) -> Enrolled | None:
        await voices.arm(device, alana, 3, later(db_url, -1))
        return await voices.enrol(device, PRINT)

    assert with_voices(db_url, body) is None
    assert scalar(db_url, "SELECT count(*) FROM voice_enrolments") == 0
    assert scalar(db_url, "SELECT count(*) FROM voiceprints") == 0


def test_arming_again_replaces_and_a_device_of_another_household_is_refused(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url, "away")
    alana, sam, stranger = person(db_url, home), person(db_url, home), person(db_url, elsewhere)
    device = satellite_row(db_url, home).device.id

    async def body(voices: PostgresVoices) -> Enrolled | None:
        await voices.arm(device, alana, 5, later(db_url))
        await voices.arm(device, sam, 1, later(db_url))
        for bad in ((device, stranger), (device + 1000, alana), (device, sam + 1000)):
            with pytest.raises(UnknownEnrolee):
                await voices.arm(*bad, 1, later(db_url))
        with pytest.raises(ValueError):
            await voices.arm(device, alana, 0, later(db_url))
        return await voices.enrol(device, PRINT)

    assert with_voices(db_url, body) == Enrolled(sam, 0)


def test_prints_are_per_person_and_model_oldest_first_and_forget_deletes_them(db_url: str) -> None:
    home, elsewhere = household(db_url), household(db_url, "away")
    alana, sam, stranger = person(db_url, home), person(db_url, home), person(db_url, elsewhere)
    device, other = satellite_row(db_url, home).device.id, satellite_row(db_url, elsewhere, name="far echo").device.id
    first, second, other_model = PRINT, Voiceprint((1.0, 0.0), "titanet", 1200), Voiceprint((1.0,), "other", 1200)

    async def body(voices: PostgresVoices) -> tuple[Any, ...]:
        for who, dev, vp in ((sam, device, first), (alana, device, first), (alana, device, second),
                             (alana, device, other_model), (stranger, other, first)):
            await voices.arm(dev, who, 1, later(db_url))
            await voices.enrol(dev, vp)
        before = await voices.prints(home, "titanet")
        await voices.arm(device, alana, 3, later(db_url))
        gone = await voices.forget(alana)
        return before, gone, await voices.prints(home, "titanet"), await voices.enrol(device, PRINT)

    before, gone, after, armed = with_voices(db_url, body)
    assert [p.person_id for p in before] == sorted([alana, sam])
    by_person = {p.person_id: p for p in before}
    assert by_person[alana].vectors == (pytest.approx((0.6, 0.8)), (1.0, 0.0))
    assert (gone, armed) == (3, None), "every model's prints go, and the enrolment armed for them"
    assert [(p.person_id, p.vectors) for p in after] == [(sam, (pytest.approx((0.6, 0.8)),))]


def test_removing_a_person_removes_their_prints(db_url: str) -> None:
    home = household(db_url)
    alana, device = person(db_url, home), satellite_row(db_url, home).device.id

    async def body(voices: PostgresVoices) -> None:
        await voices.arm(device, alana, 2, later(db_url))
        await voices.enrol(device, PRINT)

    with_voices(db_url, body)
    scalar(db_url, "DELETE FROM people WHERE id = %s RETURNING id", (alana,))
    assert scalar(db_url, "SELECT count(*) FROM voiceprints") == 0
    assert scalar(db_url, "SELECT count(*) FROM voice_enrolments") == 0


def test_no_database_is_voices_unavailable() -> None:
    voices = PostgresVoices(NullDatabase())

    async def body() -> None:
        for call in (voices.prints(1, "m"), voices.arm(1, 1, 1, datetime.now()), voices.enrol(1, PRINT),
                     voices.forget(1)):
            with pytest.raises(VoicesUnavailable):
                await call

    asyncio.run(body())
