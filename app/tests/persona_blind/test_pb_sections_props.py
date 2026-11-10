"""Properties of `ashley.persona.sections.parse` and `render` over generated persona files: what parse reads back is what
was written, render with no override is the file less its markers, and an override reaches exactly the `allowed`
sections whose ids it names."""

import string
from datetime import UTC, datetime

from hypothesis import given, settings
from hypothesis import strategies as st
from persona_blind_support import marker

from ashley.persona import sections
from ashley.skills.persona import PersonaVersion, bodies

SLUG = st.from_regex(r"[a-z][a-z0-9-]{0,11}", fullmatch=True)
LABEL = st.text(alphabet=string.ascii_letters + " ", min_size=1, max_size=20).filter(lambda s: s == s.strip() and s)
BODY = st.text(alphabet=string.ascii_letters + string.digits + " .,#-\n", min_size=1, max_size=80).filter(
    lambda s: s.strip() != "").map(str.strip)
PART = st.tuples(st.sampled_from(["allowed", "locked"]), LABEL, BODY)
FILES = st.dictionaries(SLUG, PART, min_size=1, max_size=6)

FAST = settings(max_examples=60)


def build(parts: dict[str, tuple[str, str, str]]) -> str:
    return "\n\n".join(f"{marker(i, o, label)}\n{body}" for i, (o, label, body) in parts.items()) + "\n"


@FAST
@given(FILES)
def test_parse_reads_back_what_was_written(parts: dict[str, tuple[str, str, str]]) -> None:
    got = sections.parse(build(parts))
    assert [s.id for s in got] == list(parts)
    for s in got:
        override, label, body = parts[s.id]
        assert (s.override, s.label, s.body) == (override, label, body)


@FAST
@given(FILES)
def test_render_with_no_override_is_the_bodies_one_blank_line_apart(parts: dict[str, tuple[str, str, str]]) -> None:
    text = build(parts)
    out = sections.render(text, {})
    assert out == "\n\n".join(body for _, _, body in parts.values())
    assert out == "\n".join(ln for ln in text.splitlines() if not ln.startswith("<!-- section")).strip()


@FAST
@given(FILES, st.dictionaries(SLUG, BODY, max_size=8))
def test_an_override_replaces_exactly_the_allowed_sections_it_names(
        parts: dict[str, tuple[str, str, str]], given_overrides: dict[str, str]) -> None:
    out = sections.render(build(parts), given_overrides)
    expected = [given_overrides[i] if o == "allowed" and i in given_overrides else body for i, (o, _, body) in parts.items()]
    assert out == "\n\n".join(expected)


@FAST
@given(FILES, st.dictionaries(SLUG, BODY, max_size=8))
def test_a_locked_section_never_changes_whatever_is_given(
        parts: dict[str, tuple[str, str, str]], given_overrides: dict[str, str]) -> None:
    text = build(parts)
    everything = {**given_overrides, **{i: "OVERRIDDEN" for i in parts}}
    locked = {i: p[2] for i, p in parts.items() if p[0] == "locked"}
    out = sections.render(text, everything)
    for body in locked.values():
        assert body in out
    assert sections.render(text, {i: "X" for i, p in parts.items() if p[0] == "locked"}) == sections.render(text, {})


@FAST
@given(FILES, st.dictionaries(SLUG, BODY, max_size=8))
def test_render_is_idempotent_in_its_inputs_and_ignores_override_order(
        parts: dict[str, tuple[str, str, str]], given_overrides: dict[str, str]) -> None:
    text = build(parts)
    reversed_overrides = dict(reversed(list(given_overrides.items())))
    assert sections.render(text, given_overrides) == sections.render(text, given_overrides)
    assert sections.render(text, given_overrides) == sections.render(text, reversed_overrides)


@FAST
@given(FILES, st.dictionaries(SLUG, st.one_of(st.none(), BODY), max_size=8))
def test_a_null_body_follows_the_shipped_text_and_a_set_body_pins_the_household(
        parts: dict[str, tuple[str, str, str]], heads: dict[str, str | None]) -> None:
    versions = {i: PersonaVersion(1, b, "w", "y", 0, None, 1, datetime(2026, 1, 1, tzinfo=UTC)) for i, b in heads.items()}
    applied = bodies(versions)
    assert applied == {i: b for i, b in heads.items() if b is not None}
    later = {i: (o, label, body + " Newer.") for i, (o, label, body) in parts.items()}
    out = sections.render(build(later), applied)
    for i, (o, _, body) in later.items():
        pinned = heads.get(i)
        if o == "allowed" and pinned is not None:
            assert pinned in out
        elif o == "allowed":
            assert body in out
