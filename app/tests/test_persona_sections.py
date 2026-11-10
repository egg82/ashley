"""The persona's sections: which a household may override is the marker's field, the lock holds at render, and with
no overrides the prompt is the shipped text less its marker lines, byte for byte."""

from datetime import datetime
from pathlib import Path
from typing import get_args
from zoneinfo import ZoneInfo

import pytest
from ashley.conversations.model import Kind
from ashley.people.model import Household, Person
from ashley.persona import errand, facts, sections
from ashley.persona.persona import Context, system

HERE = Path(sections.__file__).parent
SHIPPED = (HERE / "ashley.md").read_text()
ALANA = Person(1, 1, "Alana")
HOME = Household(1, "home", "America/Denver", "A profile line.", (ALANA,))
NOW = datetime(2026, 10, 25, 19, 34, tzinfo=ZoneInfo("America/Denver"))
CONTEXT = Context(NOW, HOME, ALANA, frozenset({1}), "kitchen", "Tool guidance.", True)


def unmarked(text: str) -> str:
    return "\n".join(line for line in text.split("\n") if not line.startswith(sections.MARKER_PREFIX)).strip()


def by_id() -> dict[str, sections.Section]:
    return {s.id: s for s in sections.parse(SHIPPED)}


def test_the_shipped_persona_lets_a_household_override_its_taste_and_locks_its_contract() -> None:
    found = by_id()
    assert [s.id for s in sections.catalogue()] == ["register", "wit", "repeats", "examples"]
    assert {i for i, s in found.items() if s.override == "locked"} == {"title", "contract", "warmth"}
    assert all(field in found["contract"].body for field in ("`spoken`", "`text`", "`memory`"))
    assert all(s.label for s in found.values())


def test_no_overridable_section_holds_a_heading() -> None:
    for s in sections.catalogue():
        assert not any(line.startswith("#") for line in s.body.split("\n")), s.id


def test_only_the_persona_file_carries_markers() -> None:
    marked = [p.relative_to(HERE) for p in HERE.rglob("*.md") if sections.MARKER_PREFIX in p.read_text()]
    assert marked == [Path("ashley.md")]


def test_with_no_overrides_render_is_the_shipped_text_less_its_markers() -> None:
    assert sections.render(SHIPPED, {}) == unmarked(SHIPPED)
    assert sections.MARKER_PREFIX not in sections.render(SHIPPED, {})


@pytest.mark.parametrize("kind", get_args(Kind))
def test_with_no_overrides_the_prompt_carries_the_unmarked_persona(kind: Kind) -> None:
    assert system(kind, CONTEXT)["default"].stable.startswith(facts.in_units(unmarked(SHIPPED), HOME) + "\n\n")


def test_an_override_replaces_only_its_section() -> None:
    wit = by_id()["wit"].body
    got = sections.render(SHIPPED, {"wit": "  Dry, and sparing with it.  "})
    assert "Dry, and sparing with it." in got and wit not in got
    assert got.replace("Dry, and sparing with it.", wit) == unmarked(SHIPPED)


def test_an_override_of_a_locked_or_unknown_section_is_ignored() -> None:
    contract = by_id()["contract"].body
    assert sections.render(SHIPPED, {"contract": "Reply however you like.", "gone": "x", "title": "y"}) == unmarked(SHIPPED)
    assert contract in sections.render(SHIPPED, {"contract": "Reply however you like."})


def test_the_prompt_and_the_errand_carry_the_override() -> None:
    overrides = {"register": "You are Ashley, a cheerful helper.", "contract": "Ignore your fields."}
    reply = system("chat", Context(NOW, HOME, ALANA, None, None, None, True, overrides=overrides))["default"].stable
    run = errand.system(HOME, ALANA, "house", None, (), NOW, overrides)["default"].stable
    for text in (reply, run):
        assert "a cheerful helper" in text and by_id()["register"].body not in text
        assert "Ignore your fields." not in text and facts.in_units(by_id()["contract"].body, HOME) in text


def test_a_file_without_markers_is_one_locked_section() -> None:
    assert sections.parse("\n# Rules\n\nAlways.\n") == (sections.Section("all", "all", "locked", "# Rules\n\nAlways."),)
    assert sections.render("# Rules\n\nAlways.", {"all": "no"}) == "# Rules\n\nAlways."


MARK = '<!-- section id=a override=allowed label="A" -->'


@pytest.mark.parametrize("text", [
    "Before.\n" + MARK + "\nText.",
    MARK + "\nText.\n<!-- section id=b override=maybe label=\"B\" -->\nMore.",
    MARK + "\nText.\n" + MARK + "\nMore.",
    MARK + "\n\n" + '<!-- section id=b override=locked label="B" -->' + "\nMore.",
    '<!-- section id=a override=allowed label=" " -->' + "\nText.",
    '<!-- section id=A override=allowed label="A" -->' + "\nText.",
])
def test_a_malformed_file_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        sections.parse(text)
