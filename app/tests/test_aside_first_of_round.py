from ashley.channels import aside, limits
from ashley.inference.model import ToolCall, ToolCalls, ToolResult, ToolResults


def _round(*asides: str | None) -> ToolCalls:
    return ToolCalls(tuple(ToolCall(f"c{i}", "t", {} if a is None else {aside.FIELD: a}) for i, a in enumerate(asides)))


def _results(*failed: bool) -> ToolResults:
    return ToolResults(tuple(ToolResult(f"c{i}", "not_reader: no" if f else "{}", is_error=f) for i, f in enumerate(failed)))


def test_the_aside_of_a_refused_call_is_never_the_held_line() -> None:
    assert aside.latest([_round("A"), _results(False), _round("Marking it"), _results(True)]) == "A"


def test_a_round_speaks_the_first_aside_of_a_call_that_did_not_fail() -> None:
    assert aside.latest([_round("Marking it", "Weighing supports"), _results(True, False)]) == "Weighing supports"


def test_a_round_whose_results_have_not_come_back_still_speaks() -> None:
    assert aside.latest([_round("A"), _results(True), _round("B")]) == "B"


def test_a_failed_call_of_an_earlier_round_does_not_silence_a_later_call_with_the_same_id() -> None:
    assert aside.latest([_round("A"), _results(True), _round("B"), _results(False)]) == "B"


def test_the_held_line_is_the_first_aside_of_a_round_never_a_later_call() -> None:
    assert aside.latest([_round("A", "B")]) == "A"


def test_the_latest_round_with_an_aside_speaks_and_a_blank_first_call_is_skipped() -> None:
    assert aside.latest([_round("C"), _round("", "D"), _round(None)]) == "D"


def test_no_asides_is_none() -> None:
    assert aside.latest([_round(None, "  ")]) is None


def test_a_brainstorm_turn_holds_after_a_minute_and_spoken_kinds_keep_their_short_hold() -> None:
    loaded = limits.load()
    assert loaded["brainstorm"].hold_after_s == 15 and loaded["chat"].hold_after_s == 6 and loaded["command"].hold_after_s == 4
