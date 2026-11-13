"""The Skills service through its abstract interface on Postgres: kinds, the seed, edits and their refusals, rollback,
pin and approval, the changelog, households apart, races, logging, and the Null Object."""

import asyncio

import pytest
from contract.conversations_support import run
from skills_blind_support import (
    CONFIG,
    at_info,
    events,
    everything_logged,
    now,
    put,
    reason_of,
    skills,
    started,
    world,
)

from ashley.db.pool import PoolDatabase
from ashley.skills.postgres import PostgresSkills
from ashley.skills.skills import SkillRefused, Skills, SkillsUnavailable

# --- households apart --------------------------------------------------------------------------------------------


def test_one_households_kinds_and_skills_never_reach_another(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            kind = await started(s, w.alana)
            await put(s, w.alana, kind, "alana-secret-method", 0)
            assert await reason_of(s.current(w.zed.household_id, kind)) == "unknown_kind"
            assert await reason_of(s.changelog(w.zed.household_id, kind)) == "unknown_kind"
            assert await reason_of(put(s, w.zed, kind, "x", 0)) == "unknown_kind"
            assert kind not in {k.kind for k in await s.kinds(w.zed.household_id)}
            await s.add_kind(w.zed.household_id, kind, "Zed's garden")
            assert await s.current(w.zed.household_id, kind) is None
            assert (await put(s, w.zed, kind, "zed-method", 0)).version == 1
            assert (await now(s, w.alana.household_id, kind)).body == "alana-secret-method"
            assert [v.body for v in await s.changelog(w.zed.household_id, kind)] == ["zed-method"]

    run(scenario())


# --- changelog ---------------------------------------------------------------------------------------------------


def test_the_changelog_of_an_unknown_kind_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(s.changelog(w.alana.household_id, "nope")) == "unknown_kind"

    run(scenario())


def test_the_changelog_is_the_newest_few_newest_first_while_edits_count_all(db_url: str) -> None:
    w = world(db_url)
    total = CONFIG.changelog_read + 3

    async def scenario() -> None:
        async with skills(db_url) as s:
            for i in range(total):
                await put(s, w.alana, "code", f"body-{i}", i)
            log = await s.changelog(w.alana.household_id, "code")
            assert [v.version for v in log] == list(range(total, total - CONFIG.changelog_read, -1))
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.edits) == (total, total)

    run(scenario())


# --- races -------------------------------------------------------------------------------------------------------


def test_edits_from_the_same_base_make_one_version_and_the_rest_stale(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            results = await asyncio.gather(*(put(s, w.alana, "code", f"racer-{i}", 0) for i in range(6)),
                                           return_exceptions=True)
            late = [r for r in results if isinstance(r, SkillRefused)]
            assert len(late) == 5 and len(results) == 6
            assert all(e.reason == "stale" for e in late)
            assert len(await s.changelog(w.alana.household_id, "code")) == 1

    run(scenario())


# --- logging -----------------------------------------------------------------------------------------------------


def test_changes_are_logged_and_never_with_the_text(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)
    secret, note = "SECRET-BODY-zq", "SECRET-NOTE-zq"

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.add_kind(w.alana.household_id, "garden", "SECRET-LABEL-zq")
            await s.edit(w.alana.household_id, "garden", secret, note, note, 0, None, None)
            await s.pin(w.alana.household_id, "garden", True)
            made = await s.edit(w.alana.household_id, "garden", secret + "2", note, note, 1, None, None)
            await s.decide(w.alana.household_id, "garden", made.version, True)
            await s.rollback(w.alana.household_id, "garden", 1, note, None, w.alana.person_id)

    run(scenario())
    assert len(events(caplog, "skills.kind_added")) == 1
    assert len(events(caplog, "skills.edited")) == 3
    assert len(events(caplog, "skills.pinned")) == 1
    assert len(events(caplog, "skills.decided")) == 1
    assert "SECRET-" not in everything_logged(caplog)


def test_a_refused_change_logs_no_edit(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(put(s, w.alana, "code", "x", 5)) == "stale"
            assert await reason_of(put(s, w.alana, "code", "", 0)) == "bad_body"

    run(scenario())
    assert events(caplog, "skills.edited") == []


def test_adding_an_existing_kind_logs_one_start_only(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.add_kind(w.alana.household_id, "garden", "Garden")
            await s.add_kind(w.alana.household_id, "garden", "Garden")

    run(scenario())
    assert len(events(caplog, "skills.kind_added")) == 1


# --- the Null Object and an unreachable database -----------------------------------------------------------------


def test_the_null_skills_raises_unavailable_from_every_call() -> None:
    null = Skills.null()

    async def scenario() -> None:
        calls = [null.kinds(1), null.add_kind(1, "k", "K"), null.current(1, "k"),
                 null.edit(1, "k", "b", "w", "y", 0, None, None), null.rollback(1, "k", 0, "y", None, None),
                 null.changelog(1, "k"), null.pin(1, "k", True), null.decide(1, "k", 1, True)]
        for call in calls:
            with pytest.raises(SkillsUnavailable):
                await call

    run(scenario())


def test_an_unreachable_database_is_unavailable_not_a_crash() -> None:
    async def scenario() -> None:
        db = PoolDatabase("postgresql://postgres:pg@127.0.0.1:1/postgres", connect_timeout_s=0.1)
        await db.open()
        try:
            s = PostgresSkills(db, CONFIG, {})
            with pytest.raises(SkillsUnavailable):
                await s.kinds(1)
            with pytest.raises(SkillsUnavailable):
                await s.add_kind(1, "garden", "Garden")
        finally:
            await db.close()

    run(scenario())


# --- directed: the survivors of the first mutation pass --------------------------------------------------------


def test_edits_count_live_versions_only_so_a_declined_proposal_is_not_one(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            await s.pin(w.alana.household_id, "code", True)
            waiting = await put(s, w.alana, "code", "no", 1)
            await s.decide(w.alana.household_id, "code", waiting.version, False)
            await s.pin(w.alana.household_id, "code", False)
            await put(s, w.alana, "code", "two", 1)
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.edits) == (3, 2)

    run(scenario())


def test_the_newest_waiting_proposal_is_the_one_shown(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            await s.pin(w.alana.household_id, "code", True)
            await put(s, w.alana, "code", "older", 1)
            newer = await put(s, w.alana, "code", "newer", 1)
            got = await now(s, w.alana.household_id, "code")
            assert got.proposal is not None and (got.proposal.version, got.proposal.body) == (newer.version, "newer")

    run(scenario())


def test_declining_after_the_live_version_moved_on_is_allowed(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            await s.pin(w.alana.household_id, "code", True)
            waiting = await put(s, w.alana, "code", "hers", 1)
            await put(s, w.alana, "code", "theirs", 1, by=w.alana.person_id)
            assert (await s.decide(w.alana.household_id, "code", waiting.version, False)).status == "declined"

    run(scenario())


def test_the_edit_log_line_carries_ids_kind_version_status_author_and_length(
        db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    at_info(caplog)
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "12345", 0, bench_id=None, by=None)
            await put(s, w.alana, "code", "123456789", 1, by=w.alana.person_id)

    run(scenario())
    first, second = events(caplog, "skills.edited")
    assert (first["household"], first["kind"], first["version"], first["status"], first["by"], first["chars"]) == (
        w.alana.household_id, "code", 1, "live", "ashley", 5)
    assert (second["version"], second["by"], second["chars"]) == (2, "person", 9)


def test_kinds_come_back_in_slug_order(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            for slug in ("mango", "apple", "zebra"):
                await s.add_kind(w.alana.household_id, slug, slug.title())
            assert [k.kind for k in await s.kinds(w.alana.household_id)] == ["apple", "code", "mango", "zebra"]

    run(scenario())
