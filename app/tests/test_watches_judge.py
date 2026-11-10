"""The judge turns one read and a watch into one check, under the claude_session defaults."""

from ashley.criteria import condition
from ashley.watches.judge import judge
from ashley.watches.model import Baseline, Failed, Quiet, ReadFailed, Woke
from watch_job_support import SESSION, session, watch

GONE = condition.from_json([[{"kind": "gone", "negate": False}]])


def test_the_first_read_is_a_silent_baseline() -> None:
    assert judge(session("done", 5), watch()) == Baseline(session("done", 5))


def test_a_failed_read_is_failed_with_its_reason_never_gone() -> None:
    w = watch(baseline=session("working", 1), until=GONE)
    assert judge(ReadFailed("refused"), w) == Failed("refused")


def test_an_unchanged_read_is_quiet() -> None:
    w = watch(baseline=session("working", 1))
    assert judge(session("working", 1), w) == Quiet(False)


def test_a_finish_wakes_with_its_changes() -> None:
    w = watch(baseline=session("working", 1))
    got = judge(session("done", 2), w)
    assert isinstance(got, Woke) and got.items == session("done", 2) and not got.ends
    assert [(c.id, c.kind) for c in got.changes] == [("s1", "changed")]


def test_a_second_finish_wakes() -> None:
    assert isinstance(judge(session("done", 44), watch(baseline=session("done", 42))), Woke)


def test_a_look_at_the_finish_is_quiet() -> None:
    assert judge(session("idle", 42), watch(baseline=session("done", 42))) == Quiet(False)


def test_working_does_not_wake() -> None:
    assert judge(session("working", 3), watch(baseline=session("idle", 2))) == Quiet(False)


def test_blocked_wakes() -> None:
    assert isinstance(judge(session("blocked", 3), watch(baseline=session("working", 2))), Woke)


def test_idle_after_working_wakes() -> None:
    assert isinstance(judge(session("idle", 3), watch(baseline=session("working", 2))), Woke)


def test_a_herdr_restart_resetting_seq_with_the_status_unchanged_wakes() -> None:
    assert isinstance(judge(session("done", 1), watch(baseline=session("done", 42))), Woke)


def test_a_closed_session_is_gone_and_ends_a_watch_silently() -> None:
    got = judge({}, watch(baseline=session("working", 1), until=GONE))
    assert got == Quiet(True)


def test_a_closed_session_without_until_is_quiet_and_goes_on() -> None:
    assert judge({}, watch(baseline=session("working", 1))) == Quiet(False)


def test_until_holding_with_when_wakes_once_and_ends() -> None:
    closed = condition.from_json([[{"kind": "equals", "negate": False, "field": "status", "value": "done"}]])
    got = judge(session("done", 2), watch(baseline=session("working", 1), until=closed))
    assert isinstance(got, Woke) and got.ends


def test_the_defaults_are_the_kinds() -> None:
    assert watch().when == SESSION.when
