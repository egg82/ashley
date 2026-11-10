"""Pins the shipped persona under overrides: `sections.catalogue` is the `allowed` sections of the real `ashley.md`,
`persona.system` and `errand.system` render it with the household's `overrides` and apply them to `allowed` sections
only, and no marker line reaches a prompt. The real file's sections are read through `sections.parse`; no id is named."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import get_args
from zoneinfo import ZoneInfo

import pytest
from contract.turns_support import ALANA, HOUSEHOLD
from persona_blind_support import allowed_id, locked_id, shipped_sections, shipped_text, without_markers

from ashley.conversations.model import Kind
from ashley.persona import errand, persona, sections

MARK = "zqOVERRIDE9931"
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
CONTEXT = persona.Context(NOW, HOUSEHOLD, ALANA, frozenset({ALANA.id}), "kitchen", "Tool guidance.", True)
ERRAND_NOW = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)


def blank_free(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def stable_of(kind: Kind = "chat", **over: object) -> str:
    return persona.system(kind, replace(CONTEXT, **over))["default"].stable


def errand_stable(overrides: dict[str, str] | None = None) -> str:
    if overrides is None:
        return errand.system(HOUSEHOLD, ALANA, "house", None, (), ERRAND_NOW)["default"].stable
    return errand.system(HOUSEHOLD, ALANA, "house", None, (), ERRAND_NOW, overrides=overrides)["default"].stable


# --- the shipped file ------------------------------------------------------------------------------------------------


def test_the_shipped_persona_parses_with_both_kinds_of_section() -> None:
    got = shipped_sections()
    assert {s.override for s in got} == {"allowed", "locked"}
    assert len({s.id for s in got}) == len(got)


def test_the_catalogue_is_the_allowed_sections_of_the_shipped_file_in_file_order() -> None:
    assert sections.catalogue() == tuple(s for s in shipped_sections() if s.override == "allowed")
    assert sections.catalogue()


def test_the_shipped_text_renders_as_itself_less_its_marker_lines() -> None:
    out = sections.render(shipped_text(), {})
    assert "<!-- section" not in out
    assert blank_free(out) == blank_free(without_markers(shipped_text()))


# --- persona.system ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", get_args(Kind))
def test_with_no_overrides_the_prompt_carries_the_shipped_persona_and_no_marker_line(kind: Kind) -> None:
    for variant, prompt in persona.system(kind, CONTEXT).items():
        assert not any(ln.startswith("<!-- section") for ln in prompt.stable.splitlines()), variant
    assert persona.system(kind, CONTEXT) == persona.system(kind, replace(CONTEXT, overrides=persona.NO_OVERRIDES))
    assert sections.render(shipped_text(), {}) in persona.system(kind, CONTEXT)["default"].stable


def test_an_override_of_an_allowed_section_replaces_its_shipped_body() -> None:
    target = next(s for s in sections.catalogue() if s.id == allowed_id())
    plain = stable_of()
    changed = stable_of(overrides={target.id: MARK})
    assert target.body in plain and MARK not in plain
    assert MARK in changed and target.body not in changed
    assert changed == plain.replace(target.body, MARK)


def test_overrides_reach_every_kind_and_every_variant() -> None:
    for kind in get_args(Kind):
        out = persona.system(kind, replace(CONTEXT, overrides={allowed_id(): MARK}))
        assert out and all(MARK in p.stable for p in out.values())


def test_an_override_of_a_locked_section_never_reaches_the_prompt() -> None:
    assert stable_of(overrides={locked_id(): MARK}) == stable_of()


def test_an_override_keyed_by_an_id_the_shipped_text_does_not_have_is_ignored() -> None:
    assert stable_of(overrides={"retired-section-id": MARK}) == stable_of()


def test_overrides_keyed_by_every_locked_id_and_the_kind_names_change_nothing() -> None:
    locked = {s.id: MARK for s in shipped_sections() if s.override == "locked"}
    kinds = {k: MARK for k in (*get_args(Kind), "errand", "kinds", "default") if k not in locked}
    assert stable_of(overrides={**locked, **kinds}) == stable_of()
    for kind in get_args(Kind):
        assert persona.system(kind, replace(CONTEXT, overrides={**locked, **kinds})) == persona.system(kind, CONTEXT)


def test_the_contract_sections_survive_an_override_of_every_allowed_one() -> None:
    every = {s.id: MARK for s in sections.catalogue()}
    out = stable_of(overrides=every)
    for s in shipped_sections():
        if s.override == "locked":
            assert s.body in out


def test_an_override_changes_only_the_stable_layer_and_is_deterministic() -> None:
    a = persona.system("chat", replace(CONTEXT, overrides={allowed_id(): MARK}))
    b = persona.system("chat", replace(CONTEXT, overrides={allowed_id(): MARK}))
    plain = persona.system("chat", CONTEXT)
    assert a == b
    assert a["default"].moment == plain["default"].moment


def test_an_override_with_surrounding_whitespace_renders_stripped() -> None:
    assert stable_of(overrides={allowed_id(): f"\n  {MARK}  \n"}) == stable_of(overrides={allowed_id(): MARK})


# --- errand.system ----------------------------------------------------------------------------------------------------


def test_the_errand_prompt_takes_the_households_override_of_an_allowed_section() -> None:
    target = next(s for s in sections.catalogue() if s.id == allowed_id())
    plain = errand_stable()
    assert target.body in plain
    changed = errand_stable({target.id: MARK})
    assert MARK in changed and target.body not in changed
    assert errand_stable({}) == plain


def test_the_errand_prompt_ignores_a_locked_or_unknown_id() -> None:
    assert errand_stable({locked_id(): MARK, "retired-section-id": MARK}) == errand_stable()
