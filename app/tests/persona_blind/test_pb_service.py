"""Pins PersonaOverrides and PersonaWriter on a real database, as the wiring registers them: versions are append-only
and numbered per household and section, a revert is a new version, a null body is "the shipped text", every refusal
reason, locked and unknown ids refused and never stored, households apart, concurrent writers, logging without text,
and the Null Objects."""

import asyncio
import logging
from typing import Any

import pytest
from contract.conversations_support import household, person, run
from persona_blind_support import (
    CONFIG,
    allowed_id,
    locked_id,
    persona_services,
    second_allowed_id,
    events,
    everything_logged,
    shipped_text,
)

from ashley import services
from ashley.persona import sections
from ashley.skills.persona import NullPersonaOverrides, PersonaOverrides, PersonaUnavailable, bodies
from ashley.skills.persona_write import NullPersonaWriter, PersonaRefused, PersonaWriter

SECRET = "zqSECRETBODY4417"


async def refused(call: Any) -> str:
    try:
        await call
    except PersonaRefused as e:
        return e.reason
    raise AssertionError("not refused")


class Home:
    def __init__(self, url: str) -> None:
        self.hid = household(url, "home")
        self.alana = person(url, self.hid, "Alana")
        self.sam = person(url, self.hid, "Sam")
        self.other_hid = household(url, "next door")
        self.zed = person(url, self.other_hid, "Zed")


def scenario_test(url: str, body: Any) -> None:
    async def go() -> None:
        async with persona_services(url) as (read, write):
            await body(Home(url), read, write)

    run(go(), 40.0)


# --- a first edit and what reads see --------------------------------------------------------------------------------


def test_an_edit_is_version_one_live_at_once_and_read_back_with_its_fields(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        assert await read.heads(h.hid) == {}
        assert await read.changelog(h.hid, sec) == ()
        assert await write.edit(h.hid, sec, "Blunt.", "less fluff", 0, h.alana) == 1
        heads = await read.heads(h.hid)
        assert set(heads) == {sec}
        v = heads[sec]
        assert (v.version, v.body, v.why, v.base_version, v.restored_from, v.person_id) == (
            1, "Blunt.", "less fluff", 0, None, h.alana)
        assert v.what and v.at.tzinfo is not None
        assert bodies(heads) == {sec: "Blunt."}
        assert await read.changelog(h.hid, sec) == (v,)

    scenario_test(db_url, body)


def test_versions_are_numbered_from_one_per_household_and_section(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        a, b = allowed_id(), second_allowed_id()
        assert await write.edit(h.hid, a, "A1", "w", 0, h.alana) == 1
        assert await write.edit(h.hid, a, "A2", "w", 1, h.sam) == 2
        assert await write.edit(h.hid, b, "B1", "w", 0, h.alana) == 1
        assert await write.edit(h.other_hid, a, "Z1", "w", 0, h.zed) == 1
        assert [v.version for v in await read.changelog(h.hid, a)] == [2, 1]
        assert [v.version for v in await read.changelog(h.hid, b)] == [1]

    scenario_test(db_url, body)


def test_the_changelog_is_newest_first_and_keeps_every_version(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        for n in range(3):
            await write.edit(h.hid, sec, f"B{n}", f"why {n}", n, h.alana)
        log = await read.changelog(h.hid, sec)
        assert [v.body for v in log] == ["B2", "B1", "B0"]
        assert [v.base_version for v in log] == [2, 1, 0]
        assert (await read.heads(h.hid))[sec] == log[0]

    scenario_test(db_url, body)


def test_the_changelog_reads_at_most_the_configured_newest_versions(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        total = CONFIG.changelog_read + 3
        for n in range(total):
            await write.edit(h.hid, sec, f"B{n}", "w", n, h.alana)
        log = await read.changelog(h.hid, sec)
        assert [v.version for v in log] == list(range(total, total - CONFIG.changelog_read, -1))

    scenario_test(db_url, body)


# --- refusals: nothing changes ----------------------------------------------------------------------------------------


def test_a_locked_or_unknown_section_is_refused_locked_and_nothing_is_stored(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        for sec in (locked_id(), "no-such-section", "voice-of-nobody"):
            assert await refused(write.edit(h.hid, sec, "X", "w", 0, h.alana)) == "locked", sec
            assert await refused(write.revert(h.hid, sec, 0, "w", 0, h.alana)) == "locked", sec
            assert await read.changelog(h.hid, sec) == ()
        assert await read.heads(h.hid) == {}

    scenario_test(db_url, body)


def test_which_sections_are_locked_follows_the_shipped_markers_not_the_names(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        locked = [s.id for s in sections.parse(shipped_text()) if s.override == "locked"]
        allowed = [s.id for s in sections.catalogue()]
        assert locked and allowed
        for sec in locked:
            assert await refused(write.edit(h.hid, sec, "X", "w", 0, h.alana)) == "locked", sec
        for n, sec in enumerate(allowed):
            assert await write.edit(h.hid, sec, f"X{n}", "w", 0, h.alana) == 1, sec

    scenario_test(db_url, body)


@pytest.mark.parametrize("bad", ["", "   ", "\n\t ", "a\x00b", "x" * (CONFIG.max_body_chars + 1)])
def test_a_blank_nul_or_overlong_body_is_refused_bad_body(db_url: str, bad: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        assert await refused(write.edit(h.hid, allowed_id(), bad, "w", 0, h.alana)) == "bad_body"
        assert await read.heads(h.hid) == {}

    scenario_test(db_url, body)


def test_a_body_of_exactly_the_longest_length_is_accepted(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        text = "y" * CONFIG.max_body_chars
        assert await write.edit(h.hid, allowed_id(), text, "w", 0, h.alana) == 1
        assert await refused(write.edit(h.hid, allowed_id(), text + "y", "w", 1, h.alana)) == "bad_body"

    scenario_test(db_url, body)


@pytest.mark.parametrize("bad", ["", "  ", "n\x00ote", "n" * (CONFIG.max_note_chars + 1)])
def test_a_blank_nul_or_overlong_note_is_refused_bad_note(db_url: str, bad: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        assert await refused(write.edit(h.hid, allowed_id(), "Blunt.", bad, 0, h.alana)) == "bad_note"
        assert await write.edit(h.hid, allowed_id(), "Blunt.", "fine", 0, h.alana) == 1
        assert await refused(write.revert(h.hid, allowed_id(), 0, bad, 1, h.alana)) == "bad_note"
        assert [v.version for v in await read.changelog(h.hid, allowed_id())] == [1]

    scenario_test(db_url, body)


def test_the_same_body_again_is_refused_unchanged(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        await write.edit(h.hid, sec, "Blunt.", "w", 0, h.alana)
        assert await refused(write.edit(h.hid, sec, "Blunt.", "again", 1, h.sam)) == "unchanged"
        assert [v.version for v in await read.changelog(h.hid, sec)] == [1]

    scenario_test(db_url, body)


def test_a_base_version_that_is_not_the_newest_is_refused_stale_and_nothing_changes(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        await write.edit(h.hid, sec, "One.", "w", 0, h.alana)
        await write.edit(h.hid, sec, "Two.", "w", 1, h.alana)
        for base in (0, 1, 3):
            assert await refused(write.edit(h.hid, sec, "Three.", "w", base, h.alana)) == "stale", base
            assert await refused(write.revert(h.hid, sec, 1, "w", base, h.alana)) == "stale", base
        assert (await read.heads(h.hid))[sec].body == "Two."
        assert len(await read.changelog(h.hid, sec)) == 2

    scenario_test(db_url, body)


def test_a_first_edit_made_against_a_version_that_does_not_exist_is_stale(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        assert await refused(write.edit(h.hid, allowed_id(), "X", "w", 1, h.alana)) == "stale"

    scenario_test(db_url, body)


# --- revert -----------------------------------------------------------------------------------------------------------


def test_a_revert_is_a_new_version_that_copies_the_old_body_and_names_its_source(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        await write.edit(h.hid, sec, "One.", "w", 0, h.alana)
        await write.edit(h.hid, sec, "Two.", "w", 1, h.alana)
        assert await write.revert(h.hid, sec, 1, "back", 2, h.sam) == 3
        log = await read.changelog(h.hid, sec)
        assert [v.version for v in log] == [3, 2, 1]
        assert [v.body for v in log] == ["One.", "Two.", "One."]
        assert (log[0].restored_from, log[0].base_version, log[0].why, log[0].person_id) == (1, 2, "back", h.sam)
        assert log[1].restored_from is None and log[2].restored_from is None
        assert bodies(await read.heads(h.hid)) == {sec: "One."}

    scenario_test(db_url, body)


def test_a_revert_to_zero_is_a_version_with_a_null_body_and_the_section_follows_the_shipped_text(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        await write.edit(h.hid, sec, "One.", "w", 0, h.alana)
        assert await write.revert(h.hid, sec, 0, "shipped again", 1, h.alana) == 2
        heads = await read.heads(h.hid)
        assert heads[sec].version == 2 and heads[sec].body is None and heads[sec].restored_from == 0
        assert bodies(heads) == {}
        assert [v.body for v in await read.changelog(h.hid, sec)] == [None, "One."]
        later = "\n".join(f"{ln}" for ln in ["<!-- section id=" + sec + ' override=allowed label="L" -->', "Next release's text."])
        assert "Next release's text." in sections.render(later, bodies(heads))

    scenario_test(db_url, body)


def test_a_household_back_on_the_shipped_text_can_edit_again_from_that_version(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        await write.edit(h.hid, sec, "One.", "w", 0, h.alana)
        await write.revert(h.hid, sec, 0, "w", 1, h.alana)
        assert await write.edit(h.hid, sec, "One.", "w", 2, h.alana) == 3
        assert bodies(await read.heads(h.hid)) == {sec: "One."}
        assert [v.version for v in await read.changelog(h.hid, sec)] == [3, 2, 1]

    scenario_test(db_url, body)


def test_a_revert_to_a_version_that_is_not_there_or_has_no_body_is_refused(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec, other = allowed_id(), second_allowed_id()
        await write.edit(h.hid, sec, "One.", "w", 0, h.alana)
        await write.revert(h.hid, sec, 0, "w", 1, h.alana)
        await write.edit(h.hid, other, "Other.", "w", 0, h.alana)
        await write.edit(h.hid, sec, "Three.", "w", 2, h.alana)
        assert await refused(write.revert(h.hid, sec, 99, "w", 3, h.alana)) == "no_such_version"
        assert await refused(write.revert(h.hid, sec, 2, "w", 3, h.alana)) == "no_such_version"
        assert await refused(write.revert(h.hid, "no-such-section", 1, "w", 0, h.alana)) == "locked"
        assert [v.version for v in await read.changelog(h.hid, sec)] == [3, 2, 1]

    scenario_test(db_url, body)


def test_a_revert_to_what_is_already_in_force_is_refused_unchanged(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec, other = allowed_id(), second_allowed_id()
        assert await refused(write.revert(h.hid, sec, 0, "w", 0, h.alana)) == "unchanged"
        await write.edit(h.hid, sec, "One.", "w", 0, h.alana)
        await write.edit(h.hid, sec, "Two.", "w", 1, h.alana)
        await write.revert(h.hid, sec, 1, "w", 2, h.alana)
        assert await refused(write.revert(h.hid, sec, 1, "w", 3, h.alana)) == "unchanged"
        assert await refused(write.revert(h.hid, sec, 3, "w", 3, h.alana)) == "unchanged"
        await write.revert(h.hid, sec, 0, "w", 3, h.alana)
        assert await refused(write.revert(h.hid, sec, 0, "w", 4, h.alana)) == "unchanged"
        assert await read.changelog(h.hid, other) == ()

    scenario_test(db_url, body)


# --- households and concurrency ---------------------------------------------------------------------------------------


def test_one_households_text_never_reaches_another(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        await write.edit(h.hid, sec, "Alana's own.", "w", 0, h.alana)
        assert await read.heads(h.other_hid) == {}
        assert await read.changelog(h.other_hid, sec) == ()
        assert await write.edit(h.other_hid, sec, "Zed's own.", "w", 0, h.zed) == 1
        assert bodies(await read.heads(h.hid)) == {sec: "Alana's own."}
        assert bodies(await read.heads(h.other_hid)) == {sec: "Zed's own."}
        assert await write.revert(h.other_hid, sec, 0, "w", 1, h.zed) == 2
        assert bodies(await read.heads(h.hid)) == {sec: "Alana's own."}

    scenario_test(db_url, body)


def test_two_writers_from_the_same_base_leave_one_version_and_one_stale(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        won = await asyncio.gather(write.edit(h.hid, sec, "From Alana.", "w", 0, h.alana),
                                   write.edit(h.hid, sec, "From Sam.", "w", 0, h.sam), return_exceptions=True)
        assert sorted(type(r).__name__ for r in won) == ["PersonaRefused", "int"]
        loser = next(r for r in won if isinstance(r, PersonaRefused))
        assert loser.reason == "stale"
        assert [v.version for v in await read.changelog(h.hid, sec)] == [1]

    scenario_test(db_url, body)


def test_many_writers_on_different_bases_are_numbered_one_after_the_other(db_url: str) -> None:
    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        results = await asyncio.gather(*(write.edit(h.hid, sec, f"B{n}", "w", 0, h.alana) for n in range(5)),
                                       return_exceptions=True)
        made = [r for r in results if isinstance(r, int)]
        assert made == [1] and all(isinstance(r, PersonaRefused) for r in results if not isinstance(r, int))
        assert [v.version for v in await read.changelog(h.hid, sec)] == [1]

    scenario_test(db_url, body)


# --- logging ----------------------------------------------------------------------------------------------------------


def test_a_change_logs_ids_and_a_length_never_the_text(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    async def body(h: Home, read: PersonaOverrides, write: PersonaWriter) -> None:
        sec = allowed_id()
        await write.edit(h.hid, sec, SECRET, f"{SECRET}-note", 0, h.alana)
        await write.revert(h.hid, sec, 0, f"{SECRET}-why", 1, h.alana)
        with pytest.raises(PersonaRefused):
            await write.edit(h.hid, sec, SECRET, SECRET, 99, h.alana)
        await read.heads(h.hid)
        await read.changelog(h.hid, sec)
        logged = events(caplog, "persona.changed")
        assert len(logged) == 2
        assert sec in {str(v) for v in logged[0].values()} and sec in {str(v) for v in logged[1].values()}
        assert "1" in {str(v) for v in logged[0].values()} and "2" in {str(v) for v in logged[1].values()}
        assert SECRET not in everything_logged(caplog)

    scenario_test(db_url, body)


# --- the Null Objects -------------------------------------------------------------------------------------------------


def test_unwired_every_call_raises_persona_unavailable() -> None:
    async def go() -> None:
        for read in (PersonaOverrides.null(), services.get(PersonaOverrides)):
            assert isinstance(read, NullPersonaOverrides)
            with pytest.raises(PersonaUnavailable):
                await read.heads(1)
            with pytest.raises(PersonaUnavailable):
                await read.changelog(1, allowed_id())
        for write in (PersonaWriter.null(), services.get(PersonaWriter)):
            assert isinstance(write, NullPersonaWriter)
            with pytest.raises(PersonaUnavailable):
                await write.edit(1, allowed_id(), "x", "y", 0, 1)
            with pytest.raises(PersonaUnavailable):
                await write.revert(1, allowed_id(), 0, "y", 0, 1)

    run(go())


def test_the_reader_cannot_write() -> None:
    assert not any(hasattr(PersonaOverrides, name) for name in ("edit", "revert", "write", "set", "save"))
    assert not any(hasattr(PersonaOverrides.null(), name) for name in ("edit", "revert"))
