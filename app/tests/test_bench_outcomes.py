"""The outcome measures of a bench conversation (`ashley.tools.bench_outcomes`) over hand-built turns, runs and log
events: each measure moves when the behaviour it names does, and reads no text."""

from ashley.tools import bench_outcomes as bo
from ashley.tools.bench_outcomes import Event, Run, Turn, measure


def person(i: int, at: float) -> Turn:
    return Turn(i, "person", at)


def hers(i: int, at: float, follows: bool = False, answers: int | None = None) -> Turn:
    return Turn(i, "ashley", at, follows, answers)


def done(at: float, changes: int, closed: str = "answer", answers: str = "true") -> Event:
    return Event("respond.done", at, {"changes": str(changes), "closed": closed, "answers": answers})


def test_time_to_the_first_final_answer_skips_a_held_line() -> None:
    turns = [person(1, 0), hers(2, 7, follows=True), hers(3, 30), person(4, 100), hers(5, 160)]
    got = measure(turns, [], []).first_answer_s
    assert got == {1: 30.0, 4: 60.0}


def test_a_held_line_counts_unless_it_told_the_model_was_unreachable() -> None:
    turns = [person(1, 0), hers(2, 7, follows=True), hers(3, 100, follows=True), hers(4, 200)]
    told = Event("respond.ended", 100.5, {"reason": "inference_unavailable", "recovery": "told_and_kept"})
    assert measure(turns, [], [told]).held == {1: 1}
    assert measure(turns, [], []).held == {1: 2}


def test_an_empty_answer_is_one_with_no_change_after_which_the_person_spoke_again() -> None:
    turns = [person(1, 0), hers(2, 10), person(3, 20), hers(4, 30), person(5, 40)]
    got = measure(turns, [], [done(10, 0), done(30, 2)])
    assert got.empty_answers == [2]


def test_the_last_answer_with_no_change_is_not_an_empty_one_when_the_person_never_spoke_again() -> None:
    assert measure([person(1, 0), hers(2, 10)], [], [done(10, 0)]).empty_answers == []


def test_an_open_close_is_kept_when_she_changed_something_before_the_person_spoke_and_broken_when_they_spoke_first() -> None:
    turns = [person(1, 0), hers(2, 10), hers(3, 50), person(4, 100), hers(5, 110), person(6, 200)]
    events = [done(10, 0, "stood"), done(50, 3), done(110, 0, "answer", "false")]
    got = measure(turns, [], events)
    assert got.open_closes == [2, 5] and (got.kept, got.broken) == (1, 1)


def test_a_deadline_and_a_stand_are_open_and_a_plain_answer_is_not() -> None:
    turns = [person(1, 0), hers(2, 10), person(3, 20), hers(4, 30), person(5, 40), hers(6, 50)]
    got = measure(turns, [], [done(10, 1, "stood"), done(30, 1, "deadline"), done(50, 1, "answer")])
    assert got.open_closes == [2, 4]


def test_an_answer_with_no_done_line_is_unmeasured_never_zero_changes() -> None:
    got = measure([person(1, 0), hers(2, 10), person(3, 20)], [], [])
    assert got.unmeasured == 1 and got.empty_answers == []


def test_the_deliverable_is_the_first_successful_run_the_person_did_not_undo() -> None:
    turns = [person(1, 0), person(2, 100), person(3, 200)]
    runs = [Run(50, 0, 6), Run(150, 1, 6), Run(160, 0, 6)]
    assert measure(turns, runs, [], undos=[70]).deliverable == (2, 160.0)
    assert measure(turns, runs, [], undos=[55, 170]).deliverable is None


def test_ended_reasons_and_failures_are_counted() -> None:
    events = [Event("respond.ended", 1, {"reason": "inference_unavailable"}), Event("respond.failed", 2, {"reason": "x"}),
              Event("respond.ended", 3, {"reason": "inference_unavailable"})]
    got = measure([], [], events)
    assert got.ended == {"inference_unavailable": 2} and got.failed == 1


def test_logfmt_lines_parse_to_events_and_unrelated_lines_are_skipped() -> None:
    lines = ['ts=2026-11-08T18:21:34.448Z level=info event=respond.done conversation=366 changes=2 closed=stood answers=false',
             "not a log line"]
    (event,) = bo.parse_logfmt(lines)
    assert event.name == "respond.done" and event.fields["closed"] == "stood" and event.fields["answers"] == "false"
