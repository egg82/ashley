"""Pins `ashley.persona.sections.parse` and `render` on `ashley.md`-shaped text: the marker line's shape, what is
refused, which sections an override may replace (the marker's `override` field alone), and the render rules."""

import pytest
from persona_blind_support import FIXTURE, FIXTURE_ALLOWED, FIXTURE_LOCKED, marker, parsed, persona_file, without_markers

from ashley.persona import sections
from ashley.persona.sections import Section

# --- parse: the sections of a well-formed file ---------------------------------------------------------------------


def test_the_sections_come_in_file_order_with_their_marker_fields_and_stripped_bodies() -> None:
    got = sections.parse(FIXTURE)
    assert [s.id for s in got] == ["intro", "voice", "examples", "reply"]
    assert [s.override for s in got] == ["locked", "allowed", "locked", "allowed"]
    assert [s.label for s in got] == ["Intro", "Voice", "Examples", "Reply"]
    assert got[1] == Section("voice", "Voice", "allowed", "Dry and warm. Short sentences.")
    assert all(s.body == s.body.strip() and s.body for s in got)
    assert all("<!-- section" not in s.body for s in got)


def test_a_label_may_hold_spaces_and_punctuation() -> None:
    text = f'{marker("a", "allowed", "How you talk, mostly")}\nBody.\n'
    assert sections.parse(text)[0].label == "How you talk, mostly"


def test_a_file_with_no_marker_is_one_locked_section_named_all() -> None:
    got = sections.parse("# Ashley\n\nJust text.\n")
    assert got == (Section("all", got[0].label, "locked", "# Ashley\n\nJust text."),)


def test_the_lock_is_the_markers_override_field_never_the_heading_words() -> None:
    text = persona_file(
        ("a", "locked", "## Examples\n\nWit, taste, register, voice."),
        ("b", "allowed", "## Your reply\n\nThe reply's fields and their rules."),
    )
    got = parsed(text)
    assert (got["a"].override, got["b"].override) == ("locked", "allowed")
    out = sections.render(text, {"a": "OVER-A", "b": "OVER-B"})
    assert "OVER-A" not in out and "OVER-B" in out and "Wit, taste, register, voice." in out


# --- parse: what is refused ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["Wit", "1wit", "wit_x", "wit x", "-wit", "wit.x", "", "wít"])
def test_an_id_that_is_not_a_slug_is_refused(bad_id: str) -> None:
    with pytest.raises(ValueError):
        sections.parse(f'<!-- section id={bad_id} override=allowed label="L" -->\nBody.\n')


@pytest.mark.parametrize("good_id", ["a", "wit", "how-you-talk", "a1", "a-1-b"])
def test_a_slug_id_is_accepted(good_id: str) -> None:
    assert sections.parse(f'<!-- section id={good_id} override=allowed label="L" -->\nBody.\n')[0].id == good_id


def test_a_repeated_id_is_refused_even_across_override_kinds() -> None:
    text = persona_file(("wit", "allowed", "One."), ("other", "locked", "Two."), ("wit", "locked", "Three."))
    with pytest.raises(ValueError):
        sections.parse(text)


@pytest.mark.parametrize("override", ["maybe", "ALLOWED", "Locked", "", "allowed,locked", "yes"])
def test_an_override_other_than_allowed_or_locked_is_refused(override: str) -> None:
    with pytest.raises(ValueError):
        sections.parse(f'<!-- section id=a override={override} label="L" -->\nBody.\n')


@pytest.mark.parametrize("line", [
    '<!-- section id=a label="L" -->',
    '<!-- section override=allowed label="L" -->',
    '<!-- section id=a override=allowed -->',
    '<!-- section id=a override=allowed label=L -->',
    '<!-- section id=a override=allowed label="" -->',
    '<!-- section id=a override=allowed label="L" ',
    '<!-- section id=a override=allowed label="L" --> trailing words',
    '<!-- section -->',
    '<!-- section id=a override=allowed label="L" extra=1 -->',
    "<!-- section id=a override=allowed label='L' -->",
])
def test_a_line_that_opens_section_and_is_not_of_the_shape_is_refused(line: str) -> None:
    with pytest.raises(ValueError):
        sections.parse(f"{line}\nBody.\n")


def test_text_before_the_first_marker_is_refused() -> None:
    with pytest.raises(ValueError):
        sections.parse(f"# Ashley\n\n{marker('a')}\nBody.\n")


def test_a_section_with_no_text_is_refused() -> None:
    for text in (f"{marker('a')}\n{marker('b')}\nBody.\n", f"{marker('a')}\nBody.\n\n{marker('b')}\n",
                 f"{marker('a')}\n   \n\n{marker('b')}\nBody.\n", f"{marker('a')}\n"):
        with pytest.raises(ValueError):
            sections.parse(text)


def test_a_marker_shaped_line_is_not_taken_for_one_when_it_does_not_open_a_line() -> None:
    text = f"{marker('a')}\nSee the note: <!-- section is how a file is cut.\n"
    assert sections.parse(text)[0].body == "See the note: <!-- section is how a file is cut."


# --- render --------------------------------------------------------------------------------------------------------


def test_with_no_overrides_the_text_is_the_file_less_its_marker_lines() -> None:
    assert sections.render(FIXTURE, {}) == without_markers(FIXTURE)
    assert "<!-- section" not in sections.render(FIXTURE, {})


def test_an_allowed_section_takes_the_stripped_override_and_nothing_else_moves() -> None:
    out = sections.render(FIXTURE, {"voice": "\n  Blunt.  \n"})
    assert out == without_markers(FIXTURE).replace("Dry and warm. Short sentences.", "Blunt.")


def test_overrides_for_locked_or_unknown_ids_are_ignored() -> None:
    plain = sections.render(FIXTURE, {})
    for given in ({"intro": "X"}, {"examples": "X"}, {"nope": "X"}, {"all": "X"}, {"intro": "X", "examples": "Y", "zzz": "Z"}):
        assert sections.render(FIXTURE, given) == plain


def test_a_mix_applies_the_allowed_and_ignores_the_rest() -> None:
    out = sections.render(FIXTURE, {"voice": "V2", "reply": "R2", "intro": "I2", "gone": "G2"})
    assert out == without_markers(FIXTURE).replace("Dry and warm. Short sentences.", "V2").replace(
        "## Your reply\n\nOne field per medium.", "R2")


def test_an_override_does_not_reach_the_text_through_a_file_with_no_marker() -> None:
    assert sections.render("Plain.\n", {"all": "X"}) == "Plain."


def test_a_section_renamed_in_a_later_release_stops_applying() -> None:
    renamed = FIXTURE.replace("id=voice ", "id=register ")
    assert "Blunt." not in sections.render(renamed, {"voice": "Blunt."})
    assert "Blunt." in sections.render(renamed, {"register": "Blunt."})


def test_a_section_locked_in_a_later_release_stops_applying() -> None:
    locked = FIXTURE.replace("id=voice override=allowed", "id=voice override=locked")
    assert "Blunt." not in sections.render(locked, {"voice": "Blunt."})


def test_render_is_deterministic_and_independent_of_the_order_of_the_overrides() -> None:
    a = sections.render(FIXTURE, {"voice": "V", "reply": "R"})
    b = sections.render(FIXTURE, {"reply": "R", "voice": "V"})
    assert a == b == sections.render(FIXTURE, {"voice": "V", "reply": "R"})


def test_render_refuses_what_parse_refuses() -> None:
    for text in (f"stray\n{marker('a')}\nBody.\n", f"{marker('a')}\n{marker('b')}\nB\n",
                 f"{marker('a')}\nA\n{marker('a')}\nB\n", '<!-- section id=a -->\nA\n'):
        with pytest.raises(ValueError):
            sections.render(text, {})
        with pytest.raises(ValueError):
            sections.render(text, {"a": "X"})


def test_the_fixture_has_the_sections_the_tests_name() -> None:
    got = parsed(FIXTURE)
    assert {i for i, s in got.items() if s.override == "allowed"} == FIXTURE_ALLOWED
    assert {i for i, s in got.items() if s.override == "locked"} == FIXTURE_LOCKED
