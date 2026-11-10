"""The kinds file's shape: each kind says how its body is written, and a code kind names its language."""

import pytest
from ashley.workshop.rules import kinds_from

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
