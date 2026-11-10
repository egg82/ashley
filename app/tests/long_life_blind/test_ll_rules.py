"""`undo_window` is a required limit of the rules: at least 1, in `workshop.json`."""

import json

import pytest
from ashley.workshop import rules as rules_module
from ashley.workshop.rules import load, rules_from

KINDS = {"note": {"family": "stored", "label": "Note", "max_chars": 10, "format": "plain"}}
LIMITS = {"max_pieces": 3, "title_max_chars": 5, "recent_commands": 4, "undo_window": 9}


def test_the_window_comes_from_the_limits() -> None:
    assert rules_from(KINDS, LIMITS).undo_window == 9
    assert rules_from(KINDS, {**LIMITS, "undo_window": 1}).undo_window == 1


def test_a_limits_file_without_a_window_is_refused() -> None:
    without = {k: v for k, v in LIMITS.items() if k != "undo_window"}
    with pytest.raises(ValueError):
        rules_from(KINDS, without)


@pytest.mark.parametrize("bad", [0, -1, 1.5, "9", None, True])
def test_a_window_below_one_or_not_an_integer_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        rules_from(KINDS, {**LIMITS, "undo_window": bad})


def test_the_shipped_limits_name_a_window() -> None:
    assert load().undo_window >= 1
    shipped = json.loads(rules_module.LIMITS_FILE.read_text())
    assert isinstance(shipped["undo_window"], int) and shipped["undo_window"] >= 1
