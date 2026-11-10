"""A key is deleted only when seen orphaned on two passes past grace; the pass's findings are rows in Postgres."""

from datetime import timedelta

import psycopg
from ashley.files.orphans import PostgresCandidates
from files_sweep_blind_support import GRACE, OLD, go, key, rig


def rows(url: str) -> dict[str, object]:
    with psycopg.connect(url) as conn:
        return dict(conn.execute("SELECT object_key, first_seen FROM file_orphans").fetchall())


def test_the_first_sight_deletes_nothing_and_the_second_deletes_from_every_site(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url, sites=3) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            first = await r.pass_()
            assert r.holders(key(1)) == [True, True, True]
            assert first is not None and first.deleted == 0
            second = await r.pass_()
            assert r.holders(key(1)) == [False, False, False]
            assert second is not None and second.deleted == 3

    go(scenario())


def test_the_findings_are_rows_in_postgres_and_another_pod_carries_on_from_them(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=OLD)
            await r.pass_()
            assert set(rows(db_url)) == {key(1)}
            r.candidates = PostgresCandidates()
            await r.pass_()
            assert not r.holders(key(1))[0]

    go(scenario())


def test_candidates_are_exactly_the_old_unreferenced_keys_of_the_pass(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            kept, _ = await r.file(await r.bench())
            r.age_everything(OLD)
            r.sites[0].keep(key(1), age=OLD)
            r.sites[0].keep(key(2), age=timedelta(minutes=1))
            await r.pass_()
            assert await r.candidates.load() == frozenset({key(1)})
            assert set(rows(db_url)) == {key(1)}
            assert kept not in rows(db_url)

    go(scenario())


def test_a_key_that_stays_orphaned_keeps_its_first_seen(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.candidates.save(frozenset({key(1), key(2)}))
            before = rows(db_url)
            await r.candidates.save(frozenset({key(1), key(3)}))
            after = rows(db_url)
            assert set(after) == {key(1), key(3)}
            assert after[key(1)] == before[key(1)]

    go(scenario())


def test_save_replaces_the_candidates_and_load_reads_them_back(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            assert await r.candidates.load() == frozenset()
            await r.candidates.save(frozenset({key(1), key(2)}))
            assert await r.candidates.load() == frozenset({key(1), key(2)})
            await r.candidates.save(frozenset())
            assert await r.candidates.load() == frozenset()
            assert rows(db_url) == {}

    go(scenario())


def test_a_key_that_is_referenced_again_loses_its_candidacy_and_needs_two_fresh_passes(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            k, piece = await r.file(b)
            await r.remove(b, piece)
            for _ in range(3):
                await r.note(b)
            r.age_everything(OLD)
            await r.pass_()
            assert k in await r.candidates.load()
            again, _ = await r.file(b)
            assert again == k
            await r.pass_()
            assert k not in await r.candidates.load() and r.holders(k) == [True, True]
            await r.passes(2)
            assert r.holders(k) == [True, True]

    go(scenario())


def test_a_key_young_on_the_first_pass_is_not_deleted_on_the_second_though_old_by_then(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=GRACE - timedelta(seconds=10))
            await r.pass_()
            r.clock.advance(timedelta(seconds=60))
            await r.pass_()
            assert r.holders(key(1))[0]
            await r.pass_()
            assert not r.holders(key(1))[0]

    go(scenario())


def test_a_key_that_vanished_between_passes_is_forgotten(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=OLD)
            await r.pass_()
            await r.sites[0].delete(key(1))
            await r.pass_()
            r.sites[0].keep(key(1), age=timedelta(0))
            await r.pass_()
            assert r.holders(key(1))[0]

    go(scenario())
