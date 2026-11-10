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

# --- rollback ----------------------------------------------------------------------------------------------------


def test_rollback_to_zero_is_the_seed_again_as_a_new_version(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "edited", 0)
            made = await s.rollback(w.alana.household_id, "code", 0, "it was worse", None, w.sam.person_id)
            assert (made.version, made.status) == (2, "live")
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.body, got.edits) == (2, CODE.body, 2)
            top = (await s.changelog(w.alana.household_id, "code"))[0]
            assert (top.version, top.restored_from, top.why, top.person_id, top.body, top.base_version) == (
                2, 0, "it was worse", w.sam.person_id, CODE.body, 1)
            assert top.what.startswith("Rolled back to")

    run(scenario())


def test_rollback_to_an_earlier_live_version_copies_its_body_and_keeps_every_version(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            for i, body in enumerate(["v1", "v2", "v3"]):
                await put(s, w.alana, "code", body, i)
            made = await s.rollback(w.alana.household_id, "code", 1, "back", None, None)
            assert made.version == 4
            got = await now(s, w.alana.household_id, "code")
            assert (got.body, got.version, got.edits) == ("v1", 4, 4)
            log = await s.changelog(w.alana.household_id, "code")
            assert [(v.version, v.body) for v in log] == [(4, "v1"), (3, "v3"), (2, "v2"), (1, "v1")]
            assert (log[0].restored_from, log[0].what) == (1, "Rolled back to version 1")
            assert all(v.restored_from is None for v in log[1:])

    run(scenario())


@pytest.mark.parametrize("target", [5, 99, -1])
def test_rollback_to_a_version_that_never_existed_is_refused(db_url: str, target: int) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            assert await reason_of(s.rollback(w.alana.household_id, "code", target, "why", None, None)) == "no_such_version"

    run(scenario())


def test_rollback_to_a_version_that_was_only_proposed_or_declined_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            await s.pin(w.alana.household_id, "code", True)
            first = await put(s, w.alana, "code", "waiting", 1)
            assert await reason_of(s.rollback(w.alana.household_id, "code", first.version, "why", None, None)) == "no_such_version"
            await s.decide(w.alana.household_id, "code", first.version, False)
            assert await reason_of(s.rollback(w.alana.household_id, "code", first.version, "why", None, None)) == "no_such_version"

    run(scenario())


def test_rollback_to_zero_of_a_kind_with_no_seed_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            kind = await started(s, w.alana)
            await put(s, w.alana, kind, "one", 0)
            assert await reason_of(s.rollback(w.alana.household_id, kind, 0, "why", None, None)) == "no_such_version"

    run(scenario())


def test_rollback_to_the_text_already_live_is_unchanged(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            assert await reason_of(s.rollback(w.alana.household_id, "code", 1, "why", None, None)) == "unchanged"
            await s.rollback(w.alana.household_id, "code", 0, "why", None, None)
            assert await reason_of(s.rollback(w.alana.household_id, "code", 0, "why", None, None)) == "unchanged"

    run(scenario())


def test_rollback_with_a_bad_note_or_unknown_kind_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            for why in ("", "x" * (CONFIG.max_note_chars + 1), "a\x00b"):
                assert await reason_of(s.rollback(w.alana.household_id, "code", 0, why, None, None)) == "bad_note"
            assert await reason_of(s.rollback(w.alana.household_id, "nope", 0, "why", None, None)) == "unknown_kind"
            assert (await now(s, w.alana.household_id, "code")).version == 1

    run(scenario())


# --- pin, proposals ----------------------------------------------------------------------------------------------


def test_her_edit_of_a_pinned_kind_waits_as_a_proposal_and_does_not_load(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "live-1", 0)
            await s.pin(w.alana.household_id, "code", True)
            made = await put(s, w.alana, "code", "proposed-2", 1)
            assert (made.version, made.status) == (2, "proposed")
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.body, got.pinned, got.edits) == (1, "live-1", True, 1)
            assert got.proposal is not None
            assert (got.proposal.version, got.proposal.body, got.proposal.status, got.proposal.person_id) == (
                2, "proposed-2", "proposed", None)
            log = await s.changelog(w.alana.household_id, "code")
            assert [(v.version, v.status) for v in log] == [(2, "proposed"), (1, "live")]

    run(scenario())


def test_a_persons_edit_of_a_pinned_kind_is_live_at_once(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.pin(w.alana.household_id, "code", True)
            made = await put(s, w.alana, "code", "by-person", 0, by=w.alana.person_id)
            assert (made.version, made.status) == (1, "live")
            got = await now(s, w.alana.household_id, "code")
            assert (got.body, got.proposal) == ("by-person", None)

    run(scenario())


def test_her_rollback_of_a_pinned_kind_is_a_proposal_a_persons_is_live(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            await s.pin(w.alana.household_id, "code", True)
            hers = await s.rollback(w.alana.household_id, "code", 0, "why", None, None)
            assert hers.status == "proposed"
            assert (await now(s, w.alana.household_id, "code")).body == "one"
            theirs = await s.rollback(w.alana.household_id, "code", 0, "why", None, w.alana.person_id)
            assert theirs.status == "live"
            assert (await now(s, w.alana.household_id, "code")).body == CODE.body

    run(scenario())


def test_pin_is_the_households_and_unpinning_makes_her_edits_live_again(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.pin(w.alana.household_id, "code", True)
            assert (await now(s, w.sam.household_id, "code")).pinned is True
            assert (await now(s, w.zed.household_id, "code")).pinned is False
            assert (await put(s, w.zed, "code", "zed-edit", 0)).status == "live"
            await s.pin(w.alana.household_id, "code", False)
            assert (await now(s, w.alana.household_id, "code")).pinned is False
            assert (await put(s, w.alana, "code", "now-live", 0)).status == "live"

    run(scenario())


def test_pinning_twice_and_unpinning_twice_hold(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.pin(w.alana.household_id, "code", True)
            await s.pin(w.alana.household_id, "code", True)
            assert (await now(s, w.alana.household_id, "code")).pinned is True
            await s.pin(w.alana.household_id, "code", False)
            await s.pin(w.alana.household_id, "code", False)
            assert (await now(s, w.alana.household_id, "code")).pinned is False

    run(scenario())


def test_unpinning_changes_nothing_that_waits(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.pin(w.alana.household_id, "code", True)
            await put(s, w.alana, "code", "waiting", 0)
            await s.pin(w.alana.household_id, "code", False)
            got = await now(s, w.alana.household_id, "code")
            assert got.proposal is not None and got.proposal.body == "waiting"
            assert (got.version, got.body) == (0, CODE.body)

    run(scenario())


def test_pin_of_an_unknown_kind_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            assert await reason_of(s.pin(w.alana.household_id, "nope", True)) == "unknown_kind"

    run(scenario())


def test_pin_of_a_started_kind_with_no_skill_holds(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            kind = await started(s, w.alana)
            await s.pin(w.alana.household_id, kind, True)
            assert (await put(s, w.alana, kind, "first", 0)).status == "proposed"

    run(scenario())


def test_approving_a_proposal_makes_it_live(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await s.pin(w.alana.household_id, "code", True)
            made = await put(s, w.alana, "code", "hers", 0)
            done = await s.decide(w.alana.household_id, "code", made.version, True)
            assert (done.version, done.status) == (made.version, "live")
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.body, got.proposal, got.edits) == (1, "hers", None, 1)
            assert (await s.changelog(w.alana.household_id, "code"))[0].status == "live"
            assert (await put(s, w.alana, "code", "next", 1)).status == "proposed"

    run(scenario())


def test_declining_a_proposal_leaves_the_live_text_and_marks_it_declined(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "live", 0)
            await s.pin(w.alana.household_id, "code", True)
            made = await put(s, w.alana, "code", "hers", 1)
            done = await s.decide(w.alana.household_id, "code", made.version, False)
            assert done.status == "declined"
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.body, got.proposal, got.edits) == (1, "live", None, 1)
            assert [(v.version, v.status) for v in await s.changelog(w.alana.household_id, "code")] == [
                (2, "declined"), (1, "live")]
            assert (await put(s, w.alana, "code", "again", 1)).version == 3

    run(scenario())


def test_deciding_a_version_that_is_not_waiting_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "live", 0)
            await s.pin(w.alana.household_id, "code", True)
            waiting = await put(s, w.alana, "code", "hers", 1)
            await s.decide(w.alana.household_id, "code", waiting.version, False)
            for version in (1, waiting.version, 9, 0):
                for approve in (True, False):
                    assert await reason_of(s.decide(w.alana.household_id, "code", version, approve)) == "not_proposed"

    run(scenario())


def test_an_approval_after_the_live_version_moved_on_is_stale_and_changes_nothing(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await put(s, w.alana, "code", "one", 0)
            await s.pin(w.alana.household_id, "code", True)
            waiting = await put(s, w.alana, "code", "hers", 1)
            moved = await put(s, w.alana, "code", "theirs", 1, by=w.alana.person_id)
            assert moved.status == "live"
            assert await reason_of(s.decide(w.alana.household_id, "code", waiting.version, True)) == "stale"
            got = await now(s, w.alana.household_id, "code")
            assert (got.version, got.body) == (moved.version, "theirs")
            nxt = await put(s, w.alana, "code", "hers-again", moved.version)
            assert nxt.status == "proposed" and nxt.version > waiting.version

    run(scenario())


def test_a_decision_on_another_households_kind_is_refused(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with skills(db_url) as s:
            await started(s, w.alana)
            await s.pin(w.alana.household_id, "garden", True)
            waiting = await put(s, w.alana, "garden", "hers", 0)
            assert await reason_of(s.decide(w.zed.household_id, "garden", waiting.version, True)) == "unknown_kind"
            assert await reason_of(s.decide(w.alana.household_id, "nope", 1, True)) == "unknown_kind"
            assert (await s.decide(w.sam.household_id, "garden", waiting.version, True)).status == "live"

    run(scenario())


