"""The kinds file's shape: each kind says how its body is written, and a code kind names its language; and the link
kinds in the limits file, each with its label."""

import pytest
from ashley.workshop.rules import kinds_from, load, load_screen, rules_from

BASE = {"family": "stored", "label": "Note", "max_chars": 10}


def test_a_kind_carries_its_format_and_a_code_kind_its_language() -> None:
    got = kinds_from({"a": {**BASE, "format": "plain"}, "b": {**BASE, "format": "code", "language": "python"}})
    assert (got["a"].format, got["a"].language, got["b"].format, got["b"].language) == ("plain", None, "code", "python")


@pytest.mark.parametrize("entry", [
    BASE,
    {**BASE, "format": "html"},
    {**BASE, "format": "code"},
    {**BASE, "format": "code", "language": " "},
    {**BASE, "format": "markdown", "language": "python"},
])
def test_a_kind_outside_the_shape_is_refused(entry: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        kinds_from({"a": entry})


LIMITS = {"max_pieces": 3, "title_max_chars": 5, "recent_commands": 4, "undo_window": 9}


def test_link_kinds_are_read_from_the_limits_with_their_labels_and_none_when_left_out() -> None:
    got = rules_from({"a": {**BASE, "format": "plain"}}, {**LIMITS, "link_kinds": {"part_of": {"label": "Part of"}}})
    assert dict(got.link_kinds) == {"part_of": "Part of"}
    assert dict(rules_from({"a": {**BASE, "format": "plain"}}, LIMITS).link_kinds) == {}
    assert set(load().link_kinds) == {"part_of", "depends_on", "version_of"} and load_screen().link_kinds == {}


@pytest.mark.parametrize("link_kinds", [[], {"part_of": "Part of"}, {"part_of": {}}, {"part_of": {"label": " "}},
                                        {"part_of": {"label": "P", "colour": "red"}}, {" ": {"label": "P"}}])
def test_link_kinds_outside_the_shape_are_refused(link_kinds: object) -> None:
    with pytest.raises(ValueError):
        rules_from({"a": {**BASE, "format": "plain"}}, {**LIMITS, "link_kinds": link_kinds})
