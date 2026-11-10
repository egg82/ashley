"""A site that cannot be listed or deleted from is skipped and the others go on; a pass that cannot judge deletes
nothing. Logs carry ids and counts only."""

import logging

import pytest
from files_sweep_blind_support import OLD, fields_of, go, key, log_text, rig, sha


def test_a_site_that_cannot_be_listed_is_skipped_and_the_others_go_on(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url, sites=3) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            r.sites[1].no_listing = True
            await r.passes(2)
            assert r.holders(key(1)) == [False, True, False]

    go(scenario())


def test_a_copy_left_on_a_site_that_was_down_goes_once_it_is_back(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            r.sites[1].down = True
            await r.passes(2)
            assert r.holders(key(1)) == [False, True]
            r.sites[1].down = False
            await r.passes(2)
            assert r.holders(key(1)) == [False, False]

    go(scenario())


def test_a_site_that_cannot_be_deleted_from_does_not_stop_the_others(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url, sites=3) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
                s.keep(key(2), age=OLD)
            r.sites[0].no_delete = True
            await r.pass_()
            swept = await r.pass_()
            assert r.holders(key(1)) == [True, False, False] and r.holders(key(2)) == [True, False, False]
            assert swept is not None and swept.deleted == 4

    go(scenario())


def test_every_site_down_judges_nothing_and_leaves_the_candidates(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            await r.pass_()
            for s in r.sites:
                s.down = True
            assert await r.pass_() is None
            assert not any(s.of("delete") for s in r.sites)
            for s in r.sites:
                s.down = False
            assert await r.candidates.load() == frozenset({key(1)})
            assert r.holders(key(1)) == [True, True]

    go(scenario())


def test_a_site_listing_nothing_because_it_is_down_does_not_make_its_keys_look_gone(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=OLD)
            r.sites[1].down = True
            await r.passes(3)
            assert not r.holders(key(1))[0]

    go(scenario())


def test_references_that_cannot_be_read_delete_nothing(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            await r.candidates.save(frozenset({key(1)}))

            async def broken() -> frozenset[str]:
                raise RuntimeError("references unreadable")

            from ashley.files import sweep
            with caplog.at_level(logging.INFO):
                got = await sweep.run_once(r.mirror, broken, r.candidates, r.config, r.clock)
            assert got is None
            assert r.holders(key(1)) == [True, True]
            assert fields_of(caplog, "files.sweep_failed")

    go(scenario())


def test_candidates_that_cannot_be_read_or_kept_delete_nothing(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            await r.pass_()
            import psycopg
            with psycopg.connect(db_url, autocommit=True) as conn:
                conn.execute("DROP TABLE file_orphans")
            with caplog.at_level(logging.INFO):
                assert await r.pass_() is None
            assert r.holders(key(1)) == [True, True]
            assert fields_of(caplog, "files.sweep_failed")

    go(scenario())


def test_a_pass_logs_its_start_each_site_and_its_end_with_counts_and_no_key(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            b = await r.bench()
            named, _ = await r.file(b)
            r.age_everything(OLD)
            for s in r.sites:
                s.keep(key(1), age=OLD)
            await r.pass_()
            caplog.clear()
            with caplog.at_level(logging.INFO):
                await r.pass_()
            assert len(fields_of(caplog, "files.sweep_started")) == 1
            per_site = fields_of(caplog, "files.sweep_store")
            assert len(per_site) == 2
            assert all({"seen", "unreferenced", "deleted", "ms"} <= set(f) for f in per_site)
            assert [f["deleted"] for f in per_site] == [1, 1]
            assert all(f["seen"] == 2 for f in per_site) and all(f["unreferenced"] == 1 for f in per_site)
            assert len(fields_of(caplog, "files.swept")) == 1
            text = log_text(caplog)
            assert key(1) not in text and named not in text and sha(b"x") not in text
            assert "bench/" not in text
            assert not [x for x in caplog.records if x.levelno >= logging.WARNING]

    go(scenario())


def test_a_site_that_cannot_be_listed_is_logged(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[1].no_listing = True
            r.sites[0].keep(key(1), age=OLD)
            with caplog.at_level(logging.INFO):
                await r.pass_()
            assert fields_of(caplog, "files.sweep_list_failed")
            assert key(1) not in log_text(caplog)

    go(scenario())


def test_a_site_that_cannot_be_deleted_from_is_logged_without_the_key(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            r.sites[0].no_delete = True
            await r.pass_()
            with caplog.at_level(logging.INFO):
                await r.pass_()
            assert fields_of(caplog, "files.sweep_delete_failed")
            assert key(1) not in log_text(caplog)

    go(scenario())


def test_a_copy_that_could_not_be_deleted_stays_a_candidate_and_is_tried_again(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                s.keep(key(1), age=OLD)
            r.sites[0].no_delete = True
            await r.passes(2)
            assert await r.candidates.load() == frozenset({key(1)})
            r.sites[0].no_delete = False
            await r.pass_()
            assert r.holders(key(1)) == [False, False]

    go(scenario())


def test_a_site_stops_deleting_at_its_first_failure_and_the_other_site_still_deletes_all(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            for s in r.sites:
                for n in (1, 2, 3):
                    s.keep(key(n), age=OLD)
            r.sites[0].bad_delete = {key(1)}
            await r.pass_()
            swept = await r.pass_()
            assert r.sites[0].of("delete") == [key(1)]
            assert r.holders(key(2)) == [True, False] and r.holders(key(3)) == [True, False]
            assert swept is not None and swept.deleted == 3

    go(scenario())


def test_a_site_is_only_asked_to_delete_what_it_listed(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=OLD)
            r.sites[1].keep(key(2), age=OLD)
            await r.passes(2)
            assert r.sites[0].of("delete") == [key(1)] and r.sites[1].of("delete") == [key(2)]

    go(scenario())


def test_the_references_are_read_after_every_site_is_listed(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            listed: list[int] = []

            async def named() -> frozenset[str]:
                listed.append(sum(len(s.of("listing")) for s in r.sites))
                return frozenset()

            from ashley.files import sweep
            await sweep.run_once(r.mirror, named, r.candidates, r.config, r.clock)
            assert listed == [2]

    go(scenario())


def test_a_young_unreferenced_key_counts_as_seen_and_unreferenced_but_is_not_deleted(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=OLD)
            r.sites[0].keep(key(2))
            r.sites[1].keep(key(2))
            swept = await r.pass_()
            assert swept is not None and (swept.seen, swept.unreferenced, swept.deleted) == (2, 2, 0)

    go(scenario())


def test_each_sites_log_line_counts_that_sites_own_keys(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            r.sites[0].keep(key(1), age=OLD)
            r.sites[0].keep(key(2), age=OLD)
            r.sites[1].keep(key(2), age=OLD)
            with caplog.at_level(logging.INFO):
                await r.pass_()
            per_site = fields_of(caplog, "files.sweep_store")
            assert [(f["seen"], f["unreferenced"]) for f in per_site] == [(2, 2), (1, 1)]

    go(scenario())
