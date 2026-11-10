"""The per-kind limits in turns.json: the shipped file is valid for every kind, and every malformed shape is refused."""

import pytest
from ashley.channels.limits import KINDS, Limits, load, parse

GOOD = {"max_tool_rounds": 2, "max_tool_result_chars": 100, "recent_turns": 3, "relevant_turns": 1,
        "hold_after_s": 6, "deadline_s": 40.5, "carried_runs": 2, "run_script_chars": 50, "run_output_chars": 40}


def test_the_shipped_file_has_every_kind() -> None:
    assert set(load()) == set(KINDS) and len(KINDS) == 3


def test_a_well_formed_file_parses() -> None:
    assert parse({k: GOOD for k in KINDS}) == {k: Limits(2, 100, 3, 1, 6.0, 40.5, 2, 50, 40) for k in KINDS}
    assert parse({k: {**GOOD, "relevant_turns": 0} for k in KINDS})["chat"].relevant_turns == 0
    assert parse({k: {**GOOD, "max_tool_rounds": 0} for k in KINDS})["chat"].max_tool_rounds == 0
    assert parse({k: {**GOOD, "reply_chars": 300} for k in KINDS})["chat"].reply_chars == 300
    assert parse({k: GOOD for k in KINDS})["chat"].reply_chars == 0


@pytest.mark.parametrize("bad", [
    [],
    {k: GOOD for k in KINDS if k != "chat"},
    {**{k: GOOD for k in KINDS}, "other": GOOD},
    {k: {"max_tool_rounds": 2} for k in KINDS},
    {k: {**GOOD, "extra": 1} for k in KINDS},
    {k: {**GOOD, "max_tool_rounds": -1} for k in KINDS},
    {k: {**GOOD, "max_tool_result_chars": 0} for k in KINDS},
    {k: {**GOOD, "max_tool_rounds": 1.5} for k in KINDS},
    {k: {**GOOD, "max_tool_rounds": True} for k in KINDS},
    {k: {**GOOD, "max_tool_result_chars": "100"} for k in KINDS},
    {k: {**GOOD, "recent_turns": 0} for k in KINDS},
    {k: {**GOOD, "relevant_turns": -1} for k in KINDS},
    {k: {key: v for key, v in GOOD.items() if key != "recent_turns"} for k in KINDS},
    {k: {key: v for key, v in GOOD.items() if key != "deadline_s"} for k in KINDS},
    {k: {**GOOD, "hold_after_s": 0} for k in KINDS},
    {k: {**GOOD, "deadline_s": -1} for k in KINDS},
    {k: {**GOOD, "deadline_s": True} for k in KINDS},
    {k: {**GOOD, "hold_after_s": "6"} for k in KINDS},
    {k: {**GOOD, "deadline_s": float("inf")} for k in KINDS},
    {k: {**GOOD, "deadline_s": float("nan")} for k in KINDS},
    {k: {**GOOD, "carried_runs": -1} for k in KINDS},
    {k: {**GOOD, "run_script_chars": 1.5} for k in KINDS},
    {k: {**GOOD, "run_output_chars": True} for k in KINDS},
    {k: {key: v for key, v in GOOD.items() if key != "carried_runs"} for k in KINDS},
    {k: {**GOOD, "reply_chars": -1} for k in KINDS},
    {k: {**GOOD, "reply_chars": True} for k in KINDS},
])
def test_a_malformed_file_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        parse(bad)
