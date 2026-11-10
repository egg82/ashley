"""`Pace`: when a turn started and what its kind's limits are, read by the clock the tool loop is given."""

from ashley.channels.limits import Limits
from ashley.channels.pace import Pace, pace

LIMITS = Limits(max_tool_rounds=3, max_tool_result_chars=100, recent_turns=4, relevant_turns=2)


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_pace_starts_now_when_no_start_is_given() -> None:
    clock = Clock(100.0)
    made = pace(LIMITS, None, clock, "text")
    assert (made.started, made.limits, made.medium, made.wraps) == (100.0, LIMITS, "text", False)
    clock.now = 130.0
    assert made.ms() == 30_000


def test_pace_counts_from_the_start_it_is_given() -> None:
    clock = Clock(100.0)
    made = pace(LIMITS, 40.0, clock, "spoken", True)
    assert made.started == 40.0 and made.wraps is True and made.medium == "spoken"
    assert made.ms() == 60_000


def test_past_is_inclusive_of_the_limit() -> None:
    clock = Clock(10.0)
    made = Pace(0.0, clock, LIMITS, "text")
    assert made.past(10.0) is True
    assert made.past(10.5) is False
    clock.now = 10.5
    assert made.past(10.5) is True


def test_left_counts_down_and_stops_at_zero() -> None:
    clock = Clock(4.0)
    made = Pace(0.0, clock, LIMITS, "text")
    assert made.left(10.0) == 6.0
    clock.now = 25.0
    assert made.left(10.0) == 0.0


def test_ms_truncates_to_whole_milliseconds() -> None:
    made = Pace(0.0, Clock(1.2349), LIMITS, "text")
    assert made.ms() == 1234


def test_wraps_defaults_to_false() -> None:
    assert Pace(0.0, Clock(0.0), LIMITS, "text").wraps is False


def test_a_start_of_zero_is_a_start_not_a_missing_one() -> None:
    made = pace(LIMITS, 0.0, Clock(5.0), "text")
    assert made.started == 0.0
    assert made.ms() == 5000
