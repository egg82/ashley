"""What became of an agreed proposal, as a value and in her history: the record's shape for calls that ran, failed or were
not run and for an interrupted run, and the line marked as the app's that a person's agreeing turn carries into a later
turn, never words of hers."""

from datetime import UTC, datetime

import pytest
from ashley.channels.history_receipts import after, agreed_line
from ashley.conversations.model import AgreedCall, AgreedOutcome, Turn
from ashley.tools import outside_config

CFG = outside_config.load()
NOW = datetime(2026, 11, 9, tzinfo=UTC)
MIXED = AgreedOutcome((AgreedCall("Turn on the hall lamp", "ran"), AgreedCall("Open the garage", "failed"),
                       AgreedCall("Move a message", "not_run")))


def test_the_record_round_trips_each_status_and_an_interrupted_run() -> None:
    for outcome in (MIXED, AgreedOutcome(interrupted=True), AgreedOutcome()):
        assert AgreedOutcome.from_json(outcome.to_json()) == outcome
    assert MIXED.to_json() == {"interrupted": False, "calls": [
        {"summary": "Turn on the hall lamp", "status": "ran"}, {"summary": "Open the garage", "status": "failed"},
        {"summary": "Move a message", "status": "not_run"}]}


def test_an_interrupted_run_names_no_call_and_an_unknown_status_is_refused() -> None:
    with pytest.raises(ValueError):
        AgreedOutcome((AgreedCall("Turn on the hall lamp", "ran"),), interrupted=True)
    with pytest.raises(KeyError):
        AgreedOutcome.from_json({"calls": [{"summary": "x", "status": "done"}], "interrupted": False})


def test_the_history_line_gives_each_call_its_outcome_marked_as_the_apps() -> None:
    line = agreed_line(MIXED)
    assert line == CFG.history_agreed.format(items=f"Turn on the hall lamp: {CFG.agreed_ran}; "
                                                   f"Open the garage: {CFG.agreed_failed}; Move a message: {CFG.not_run}")
    assert line.startswith("[") and "not said by you" in CFG.history_agreed


def test_an_interrupted_run_has_its_own_history_line() -> None:
    assert agreed_line(AgreedOutcome(interrupted=True)) == CFG.history_agreed_interrupted


def test_an_agreeing_turn_carries_its_line_after_its_text_and_a_plain_turn_carries_nothing() -> None:
    tap = Turn(7, "person", 1, "Agreed.", NOW, agreed=MIXED)
    assert after(tap) == f"\n{agreed_line(MIXED)}"
    assert after(Turn(8, "person", 1, "Agreed.", NOW)) == ""
