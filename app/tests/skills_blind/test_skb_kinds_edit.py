"""The Skills service through its abstract interface on Postgres: kinds, the seed, edits and their refusals, rollback,
pin and approval, the changelog, households apart, races, logging, and the Null Object."""


import pytest
from contract.conversations_support import run
from skills_blind_support import (
    CODE,
    CONFIG,
    now,
    put,
    reason_of,
    skills,
    started,
    world,
)

from ashley.db.pool import PoolDatabase
from ashley.skills.seeds import Seed
from ashley.workshop import rules as workshop_rules
from ashley.workshop.postgres import PostgresWorkshop

# --- kinds -------------------------------------------------------------------------------------------------------


def test_a_household_with_no_rows_and_no_seeds_has_no_kinds(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url, seeds={}) as s:
            assert await s.kinds(w.alana.household_id) == ()

    run(scenario())


def test_a_seed_kind_exists_for_every_household(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            for owner in (w.alana, w.zed):
                assert [(k.kind, k.label) for k in await s.kinds(owner.household_id)] == [("code", "Code")]

    run(scenario())


def test_add_kind_is_the_households_alone_and_lists_with_seeds(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            made = await s.add_kind(w.alana.household_id, "electronics", "Electronics")
            assert (made.kind, made.label) == ("electronics", "Electronics")
            mine = {k.kind: k.label for k in await s.kinds(w.sam.household_id)}
            assert mine == {"code": "Code", "electronics": "Electronics"}
            assert {k.kind for k in await s.kinds(w.zed.household_id)} == {"code"}

    run(scenario())


def test_add_kind_is_idempotent_and_never_changes_a_label(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.add_kind(w.alana.household_id, "garden", "Garden")
            again = await s.add_kind(w.alana.household_id, "garden", "Something else")
            assert (again.kind, again.label) == ("garden", "Garden")
            assert [k.label for k in await s.kinds(w.alana.household_id) if k.kind == "garden"] == ["Garden"]

    run(scenario())


def test_a_households_label_wins_over_a_seeds(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.add_kind(w.alana.household_id, "code", "Programming")
            assert {k.kind: k.label for k in await s.kinds(w.alana.household_id)}["code"] == "Programming"
            assert {k.kind: k.label for k in await s.kinds(w.zed.household_id)}["code"] == "Code"

    run(scenario())


@pytest.mark.parametrize("kind", ["", "Code", "has space", "-lead", "under_score", "a/b", "x" * (CONFIG.max_slug_chars + 1),
                                  "tab\t", "café"])
def test_add_kind_refuses_a_name_that_is_not_a_slug(db_url: str, kind: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(s.add_kind(w.alana.household_id, kind, "Label")) == "bad_kind"
            assert {k.kind for k in await s.kinds(w.alana.household_id)} == {"code"}

    run(scenario())


@pytest.mark.parametrize("label", ["", "   ", "x" * (CONFIG.max_label_chars + 1), "a\x00b"])
def test_add_kind_refuses_a_bad_label(db_url: str, label: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(s.add_kind(w.alana.household_id, "garden", label)) == "bad_kind"
            assert "garden" not in {k.kind for k in await s.kinds(w.alana.household_id)}

    run(scenario())


def test_add_kind_accepts_the_longest_slug_and_label(db_url: str) -> None:
    w = world(db_url)
    slug, label = "a" * CONFIG.max_slug_chars, "L" * CONFIG.max_label_chars

    async def scenario() -> None:
        async with skills(db_url) as s:
            made = await s.add_kind(w.alana.household_id, slug, label)
            assert (made.kind, made.label) == (slug, label)
            await s.add_kind(w.alana.household_id, "7-up", "Digit first")

    run(scenario())


# --- current -----------------------------------------------------------------------------------------------------


def test_current_of_an_unknown_kind_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(s.current(w.alana.household_id, "nope")) == "unknown_kind"

    run(scenario())


def test_current_of_a_started_kind_without_a_seed_is_none(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            kind = await started(s, w.alana)
            assert await s.current(w.alana.household_id, kind) is None

    run(scenario())


def test_an_unedited_seeded_kind_reads_as_the_seed_at_version_zero(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            got = await now(s, w.alana.household_id, "code")
            assert (got.kind, got.version, got.body, got.edits, got.pinned, got.seeded_from, got.proposal) == (
                "code", 0, CODE.body, 0, False, CODE.seeded_from, None)
            assert got.changed_at is None
            assert await s.changelog(w.alana.household_id, "code") == ()

    run(scenario())


def test_an_unedited_kind_reads_whatever_seed_ships_now(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            before = await now(s, w.alana.household_id, "code")
        async with skills(db_url, seeds={"code": Seed("code", "Code", "src", "NEWER-SEED")}) as s:
            after = await now(s, w.alana.household_id, "code")
        assert (before.body, after.body, after.version) == (CODE.body, "NEWER-SEED", 0)

    run(scenario())


# --- edit --------------------------------------------------------------------------------------------------------


def test_the_first_edit_of_a_seed_is_version_one_live_and_replaces_it_for_that_household_only(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            made = await put(s, w.alana, "code", "MY-BODY", 0)
            assert (made.version, made.status) == (1, "live")
            got = await now(s, w.sam.household_id, "code")
            assert (got.version, got.body, got.edits, got.seeded_from) == (1, "MY-BODY", 1, None)
            assert got.changed_at is not None
            other = await now(s, w.zed.household_id, "code")
            assert (other.version, other.body, other.edits) == (0, CODE.body, 0)

    run(scenario())


def test_the_first_edit_of_a_kind_with_no_seed_starts_its_skill(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            kind = await started(s, w.alana)
            assert (await put(s, w.alana, kind, "first", 0)).version == 1
            got = await now(s, w.alana.household_id, kind)
            assert (got.version, got.body, got.seeded_from) == (1, "first", None)

    run(scenario())


def test_versions_number_on_from_one_per_kind(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            other = await started(s, w.alana, "garden")
            assert [(await put(s, w.alana, "code", f"b{i}", i)).version for i in range(3)] == [1, 2, 3]
            assert (await put(s, w.alana, other, "g", 0)).version == 1
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.edits) == (3, 3)

    run(scenario())


def test_the_changelog_records_what_why_author_and_base_newest_first(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0, bench_id=None, by=w.alana.person_id, what="W1", why="Y1")
            await put(s, w.alana, "code", "two", 1, bench_id=None, by=None, what="W2", why="Y2")
            log = await s.changelog(w.alana.household_id, "code")
            assert [v.version for v in log] == [2, 1]
            older, newest = log[1], log[0]
            assert (older.what, older.why, older.person_id, older.body, older.base_version, older.status,
                    older.restored_from) == ("W1", "Y1", w.alana.person_id, "one", 0, "live", None)
            assert (newest.what, newest.why, newest.person_id, newest.body, newest.base_version) == (
                "W2", "Y2", None, "two", 1)
            assert older.at <= newest.at

    run(scenario())


def test_a_change_records_the_bench_it_was_made_on(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        db = PoolDatabase(db_url)
        await db.open()
        try:
            bench = (await PostgresWorkshop(db, workshop_rules.load()).open(w.alana, "b")).id
        finally:
            await db.close()
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "x", 0, bench_id=bench)
            await put(s, w.alana, "code", "y", 1, bench_id=None)
            await s.rollback(w.alana.household_id, "code", 1, "why", bench, None)
            assert [v.bench_id for v in await s.changelog(w.alana.household_id, "code")] == [bench, None, bench]

    run(scenario())


def test_a_stale_base_version_is_refused_and_writes_nothing(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            for base in (0, 2, 99):
                assert await reason_of(put(s, w.alana, "code", f"stale-{base}", base)) == "stale"
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.body) == (1, "one")
            assert len(await s.changelog(w.alana.household_id, "code")) == 1

    run(scenario())


def test_a_nonzero_base_on_a_never_edited_kind_is_stale(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(put(s, w.alana, "code", "x", 1)) == "stale"

    run(scenario())


def test_an_edit_that_does_not_change_the_body_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(put(s, w.alana, "code", CODE.body, 0)) == "unchanged"
            await put(s, w.alana, "code", "one", 0)
            assert await reason_of(put(s, w.alana, "code", "one", 1)) == "unchanged"
            assert len(await s.changelog(w.alana.household_id, "code")) == 1

    run(scenario())


@pytest.mark.parametrize("body", ["", "a\x00b", "x" * (CONFIG.max_body_chars + 1)])
def test_a_bad_body_is_refused(db_url: str, body: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(put(s, w.alana, "code", body, 0)) == "bad_body"
            assert (await now(s, w.alana.household_id, "code")).version == 0

    run(scenario())


def test_a_body_of_exactly_the_limit_is_accepted(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert (await put(s, w.alana, "code", "x" * CONFIG.max_body_chars, 0)).status == "live"

    run(scenario())


@pytest.mark.parametrize("field", ["what", "why"])
@pytest.mark.parametrize("note", ["", "a\x00b", "x" * (CONFIG.max_note_chars + 1)])
def test_a_bad_note_is_refused(db_url: str, field: str, note: str) -> None:
    w = world(db_url)
    what, why = (note, "y") if field == "what" else ("w", note)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(s.edit(w.alana.household_id, "code", "new", what, why, 0, None, None)) == "bad_note"
            assert (await now(s, w.alana.household_id, "code")).version == 0

    run(scenario())


def test_notes_of_exactly_the_limit_are_accepted(db_url: str) -> None:
    w = world(db_url)
    note = "n" * CONFIG.max_note_chars

    async def scenario() -> None:
        async with skills(db_url) as s:
            made = await s.edit(w.alana.household_id, "code", "new", note, note, 0, None, None)
            assert made.version == 1
            log = await s.changelog(w.alana.household_id, "code")
            assert (log[0].what, log[0].why) == (note, note)

    run(scenario())


def test_edit_of_an_unknown_kind_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(put(s, w.alana, "nope", "x", 0)) == "unknown_kind"

    run(scenario())


def test_a_body_with_unicode_and_newlines_round_trips_exactly(db_url: str) -> None:
    w = world(db_url)
    body = "# Title\n\n- café ✓ \"quoted\" \\ back\n\ttabbed\n"

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", body, 0)
            assert (await now(s, w.alana.household_id, "code")).body == body

    run(scenario())


