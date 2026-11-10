"""Pins the persona page's wire contract (`ashley.api.persona_models`) through the real app on a real database: who may
call it, `PersonaDetail` as it stands after each call, the `section` and `history` field names, refusals as 409 with
their reason, a `section` that is not a slug as 422, a body outside the schema as 422, households apart, and a section
the household changed that this release no longer lets it override listed as orphaned and not used."""

from collections.abc import Generator
from typing import Any

import pytest
from persona_blind_support import CONFIG, Rig, allowed_id, build, locked_id, second_allowed_id
from respond_support import Fakes
from respond_support import wired as wired

from ashley.api.persona_models import (
    PersonaChange,
    PersonaDetail,
    PersonaEditRequest,
    PersonaRefusalBody,
    PersonaRevertRequest,
    PersonaSection,
)
from ashley.persona import sections
from ashley.persona.sections import Section

TARGET = "/api/persona"


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def detail(rig: Rig) -> PersonaDetail:
    got = rig.get(TARGET)
    assert got.status_code == 200, got.text
    return PersonaDetail.model_validate(got.json())


def answered(got: Any) -> PersonaDetail:
    assert got.status_code == 200, got.text
    return PersonaDetail.model_validate(got.json())


def refusal(got: Any) -> str:
    assert got.status_code == 409, got.text
    parsed = PersonaRefusalBody.model_validate(got.json())
    assert parsed.code == "refused"
    return str(parsed.reason)


def edit(rig: Rig, section: str, body: str = "Blunt.", base: int = 0, why: str = "less fluff") -> Any:
    return rig.put(f"{TARGET}/{section}", {"body": body, "why": why, "base_version": base})


def revert(rig: Rig, section: str, to: int, base: int, why: str = "back") -> Any:
    return rig.post(f"{TARGET}/{section}/revert", {"to_version": to, "why": why, "base_version": base})


def of(d: PersonaDetail, section: str) -> PersonaSection:
    return next(s for s in d.sections if s.section == section)


# --- the models ----------------------------------------------------------------------------------------------------


def test_the_section_model_names_its_id_section_and_its_changelog_history() -> None:
    fields = set(PersonaSection.model_fields)
    assert {"section", "label", "shipped", "override", "persona_version", "history"} <= fields
    assert not fields & {"id", "changelog"}
    assert {"persona_version", "body", "what", "why", "base_version", "restored_from", "person_id", "at"} <= set(
        PersonaChange.model_fields)
    assert {"sections", "orphaned", "body_limit", "note_limit"} <= set(PersonaDetail.model_fields)


def test_the_refusal_reasons_are_the_writers_words() -> None:
    for reason in ("locked", "bad_body", "bad_note", "unchanged", "stale", "no_such_version"):
        assert PersonaRefusalBody.model_validate({"code": "refused", "reason": reason, "detail": "d"}).reason == reason
    with pytest.raises(ValueError):
        PersonaRefusalBody.model_validate({"code": "refused", "reason": "nope", "detail": "d"})


def test_the_request_models_refuse_what_the_schema_forbids() -> None:
    for bad in ({"body": "", "why": "w", "base_version": 0}, {"body": "b", "why": "", "base_version": 0},
                {"body": "b", "why": "w", "base_version": -1}, {"body": "b\x00", "why": "w", "base_version": 0},
                {"body": "b", "why": "w", "base_version": 0, "extra": 1}, {"body": "b", "why": "w"}):
        with pytest.raises(ValueError):
            PersonaEditRequest.model_validate(bad)
    for bad in ({"to_version": -1, "why": "w", "base_version": 0}, {"to_version": 0, "why": "", "base_version": 0},
                {"to_version": 0, "why": "w", "base_version": 0, "extra": 1}, {"why": "w", "base_version": 0}):
        with pytest.raises(ValueError):
            PersonaRevertRequest.model_validate(bad)


# --- who may call it -------------------------------------------------------------------------------------------------


def test_every_route_needs_a_signed_in_person(db_url: str, wired: Fakes) -> None:
    rig = build(db_url, wired, signed_in=False)
    with rig.client:
        assert rig.get(TARGET).status_code == 401
        assert edit(rig, allowed_id()).status_code == 401
        assert revert(rig, allowed_id(), 0, 0).status_code == 401


# --- reading ---------------------------------------------------------------------------------------------------------


def test_a_household_with_no_change_sees_the_shipped_sections_in_order(rig: Rig) -> None:
    d = detail(rig)
    shipped = sections.catalogue()
    assert [s.section for s in d.sections] == [s.id for s in shipped]
    for got, want in zip(d.sections, shipped, strict=True):
        assert (got.label, got.shipped, got.override, got.persona_version, got.history) == (
            want.label, want.body, None, 0, [])
    assert d.orphaned == []
    assert (d.body_limit, d.note_limit) == (CONFIG.max_body_chars, CONFIG.max_note_chars)


def test_no_locked_section_is_offered(rig: Rig) -> None:
    assert locked_id() not in {s.section for s in detail(rig).sections}


# --- editing ---------------------------------------------------------------------------------------------------------


def test_an_edit_answers_the_detail_as_it_now_stands_and_is_the_next_read(rig: Rig) -> None:
    sec = allowed_id()
    d = answered(edit(rig, sec))
    s = of(d, sec)
    assert (s.override, s.persona_version) == ("Blunt.", 1)
    assert [(h.persona_version, h.body, h.why, h.base_version, h.restored_from) for h in s.history] == [
        (1, "Blunt.", "less fluff", 0, None)]
    assert s.shipped == next(c.body for c in sections.catalogue() if c.id == sec)
    assert detail(rig) == d


def test_other_sections_are_untouched_by_an_edit(rig: Rig) -> None:
    answered(edit(rig, allowed_id()))
    other = of(detail(rig), second_allowed_id())
    assert (other.override, other.persona_version, other.history) == (None, 0, [])


def test_the_history_is_newest_first_and_a_second_edit_is_made_against_the_first(rig: Rig) -> None:
    sec = allowed_id()
    answered(edit(rig, sec, "One."))
    s = of(answered(edit(rig, sec, "Two.", base=1)), sec)
    assert s.persona_version == 2 and s.override == "Two."
    assert [h.persona_version for h in s.history] == [2, 1]


def test_any_person_of_the_household_may_change_it_and_the_change_names_them(rig: Rig) -> None:
    sec = allowed_id()
    answered(edit(rig, sec, "From Alana."))
    rig.as_("sam")
    s = of(answered(edit(rig, sec, "From Sam.", base=1)), sec)
    assert s.history[0].person_id == rig.w.sam.id and s.history[1].person_id == rig.w.alana.id


def test_a_locked_or_unknown_section_is_409_locked_and_nothing_is_stored(rig: Rig) -> None:
    for sec in (locked_id(), "no-such-section"):
        assert refusal(edit(rig, sec)) == "locked"
        assert refusal(revert(rig, sec, 0, 0)) == "locked"
    assert all(s.persona_version == 0 for s in detail(rig).sections)


@pytest.mark.parametrize("section", ["Bad_Id", "9lives", "UPPER", "with%20space", "-dash", "a_b"])
def test_a_section_that_is_not_a_slug_is_422(rig: Rig, section: str) -> None:
    assert edit(rig, section).status_code == 422
    assert revert(rig, section, 0, 0).status_code == 422


def test_a_stale_edit_is_409_stale_and_changes_nothing(rig: Rig) -> None:
    sec = allowed_id()
    answered(edit(rig, sec, "One."))
    assert refusal(edit(rig, sec, "Two.", base=0)) == "stale"
    assert of(detail(rig), sec).override == "One."


def test_an_unchanged_body_is_409_unchanged(rig: Rig) -> None:
    sec = allowed_id()
    answered(edit(rig, sec, "One."))
    assert refusal(edit(rig, sec, "One.", base=1)) == "unchanged"


def test_a_body_over_the_limit_is_409_bad_body_and_a_note_over_it_409_bad_note(rig: Rig) -> None:
    sec = allowed_id()
    assert refusal(edit(rig, sec, "x" * (CONFIG.max_body_chars + 1))) == "bad_body"
    assert refusal(edit(rig, sec, "Blunt.", why="n" * (CONFIG.max_note_chars + 1))) == "bad_note"
    assert refusal(edit(rig, sec, "   ")) == "bad_body"
    assert of(detail(rig), sec).persona_version == 0


@pytest.mark.parametrize("body", [
    {"body": "", "why": "w", "base_version": 0},
    {"body": "b", "why": "", "base_version": 0},
    {"body": "b", "why": "w", "base_version": -1},
    {"body": "b", "why": "w"},
    {"why": "w", "base_version": 0},
    {"body": "b\u0000", "why": "w", "base_version": 0},
    {"body": "b", "why": "w", "base_version": 0, "extra": "x"},
    {"body": None, "why": "w", "base_version": 0},
    {"body": 5, "why": "w", "base_version": 0},
])
def test_a_body_outside_the_schema_is_422_and_changes_nothing(rig: Rig, body: dict[str, Any]) -> None:
    assert rig.put(f"{TARGET}/{allowed_id()}", body).status_code == 422
    assert of(detail(rig), allowed_id()).persona_version == 0


# --- reverting -------------------------------------------------------------------------------------------------------


def test_a_revert_is_a_new_version_and_zero_goes_back_to_the_shipped_text(rig: Rig) -> None:
    sec = allowed_id()
    answered(edit(rig, sec, "One."))
    answered(edit(rig, sec, "Two.", base=1))
    s = of(answered(revert(rig, sec, 1, 2)), sec)
    assert (s.override, s.persona_version, s.history[0].restored_from, s.history[0].body) == ("One.", 3, 1, "One.")
    s = of(answered(revert(rig, sec, 0, 3)), sec)
    assert (s.override, s.persona_version, s.history[0].restored_from, s.history[0].body) == (None, 4, 0, None)
    assert [h.persona_version for h in s.history] == [4, 3, 2, 1]


def test_a_revert_refusals_are_409_with_their_reason(rig: Rig) -> None:
    sec = allowed_id()
    assert refusal(revert(rig, sec, 0, 0)) == "unchanged"
    answered(edit(rig, sec, "One."))
    assert refusal(revert(rig, sec, 7, 1)) == "no_such_version"
    assert refusal(revert(rig, sec, 0, 0)) == "stale"
    assert refusal(revert(rig, sec, 1, 1)) == "unchanged"
    assert of(detail(rig), sec).persona_version == 1


def test_a_revert_body_outside_the_schema_is_422(rig: Rig) -> None:
    sec = allowed_id()
    for body in ({"to_version": -1, "why": "w", "base_version": 0}, {"to_version": 0, "why": "", "base_version": 0},
                 {"to_version": 0, "why": "w"}, {"to_version": 0, "why": "w", "base_version": 0, "x": 1}):
        assert rig.post(f"{TARGET}/{sec}/revert", body).status_code == 422


# --- households apart ------------------------------------------------------------------------------------------------


def test_another_households_text_is_never_shown_or_changed(rig: Rig) -> None:
    sec = allowed_id()
    answered(edit(rig, sec, "Alana's own."))
    rig.as_("zed")
    assert of(detail(rig), sec).override is None
    z = of(answered(edit(rig, sec, "Zed's own.")), sec)
    assert (z.override, z.persona_version) == ("Zed's own.", 1)
    rig.as_("alana")
    assert of(detail(rig), sec).override == "Alana's own."


# --- orphaned sections -----------------------------------------------------------------------------------------------


def test_a_changed_section_the_release_no_longer_offers_is_listed_orphaned_and_not_used(
        db_url: str, wired: Fakes, monkeypatch: pytest.MonkeyPatch) -> None:
    retired = "retired-section-id"
    real = sections.catalogue()
    monkeypatch.setattr(sections, "catalogue", lambda: (*real, Section(retired, "Retired", "allowed", "Old text.")))
    first = build(db_url, wired)
    with first.client:
        assert of(answered(edit(first, retired, "Household's own.")), retired).override == "Household's own."
        assert detail(first).orphaned == []
    monkeypatch.setattr(sections, "catalogue", lambda: real)
    second = build(db_url, wired, world=first.w)
    with second.client:
        d = detail(second)
        assert d.orphaned == [retired]
        assert retired not in {s.section for s in d.sections}
        assert refusal(edit(second, retired, "Again.", base=1)) == "locked"
