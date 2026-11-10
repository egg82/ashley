"""A key is deleted only when its bytes were last written at least `sweep_grace_s` ago on every site that holds it,
by the store's write time."""

from dataclasses import replace
from datetime import timedelta

from files_sweep_blind_support import CONFIG, GRACE, go, key, rig


def test_a_young_key_is_never_deleted_however_many_passes_see_it(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=GRACE - timedelta(seconds=1))
            await r.pass_()
            assert r.holders(key(1)) == [True, True]
            assert await r.candidates.load() == frozenset()

    go(scenario())


def test_a_key_exactly_the_grace_old_is_old_enough(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=GRACE)
            await r.pass_()
            assert await r.candidates.load() == frozenset({key(1)})
            await r.pass_()
            assert r.holders(key(1)) == [False, False]

    go(scenario())


def test_a_key_one_second_short_of_the_grace_is_not(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=GRACE - timedelta(seconds=1))
            await r.passes(3)
            assert r.holders(key(1))[0]

    go(scenario())


def test_the_grace_is_the_configured_one(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.config = replace(CONFIG, sweep_grace_s=100)
            r.sites[0].keep(key(1), age=timedelta(seconds=99))
            r.sites[0].keep(key(2), age=timedelta(seconds=100))
            await r.passes(2)
            assert r.holders(key(1))[0] and not r.holders(key(2))[0]

    go(scenario())


def test_a_key_young_on_one_site_is_kept_on_every_site(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=GRACE * 10)
            r.sites[1].keep(key(1), age=timedelta(minutes=1))
            await r.passes(4)
            assert r.holders(key(1)) == [True, True]

    go(scenario())


def test_a_retry_putting_old_bytes_again_restarts_their_grace(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=GRACE * 3)
            await r.pass_()
            assert await r.candidates.load() == frozenset({key(1)})
            await r.mirror.put(key(1), b"again")
            await r.pass_()
            assert r.holders(key(1)) == [True, True]
            assert await r.candidates.load() == frozenset()

    go(scenario())


def test_the_age_is_the_stores_write_time_not_when_the_sweep_first_saw_the_key(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=timedelta(0))
            await r.pass_()
            r.clock.advance(GRACE + timedelta(minutes=1))
            await r.pass_()
            assert r.holders(key(1))[0]
            await r.pass_()
            assert r.holders(key(1)) == [False, False]

    go(scenario())


def test_a_key_held_by_one_site_only_goes_from_it_when_old(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[1].keep(key(1), age=GRACE * 2)
            await r.passes(2)
            assert r.holders(key(1)) == [False, False]

    go(scenario())
