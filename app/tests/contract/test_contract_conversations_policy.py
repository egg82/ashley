"""`ashley.conversations.policy`: the state a conversation is in, as a pure function of its kind, its last activity and
now; the policy parsed from JSON, refusing every malformed shape; the shipped policy valid for every kind."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ashley.conversations import policy as policy_module
from ashley.conversations.model import Kind, State
from ashley.conversations.policy import Policy, Timing, load, parse
from conversations_support import KINDS, POLICY
from hypothesis import given, settings
from hypothesis import strategies as st

T0 = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC)
RANK: dict[State, int] = {"open": 0, "idle": 1, "closed": 2}
US = timedelta(microseconds=1)


def state_after(kind: Kind, elapsed: timedelta, policy: Policy = POLICY) -> State:
    return policy.state_of(kind, T0, T0 + elapsed)


@pytest.mark.parametrize("kind", KINDS)
def test_each_boundary_belongs_to_the_later_state(kind: Kind) -> None:
    t = POLICY.timings[kind]
    idle, closed = timedelta(seconds=t.idle_after_s), timedelta(seconds=t.closed_after_s)
    assert state_after(kind, timedelta(0)) == "open"
    assert state_after(kind, idle - US) == "open"
    assert state_after(kind, idle) == "idle"
    assert state_after(kind, closed - US) == "idle"
    assert state_after(kind, closed) == "closed"
    assert state_after(kind, closed * 1000) == "closed"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("before", [US, timedelta(seconds=1), timedelta(days=3650)])
def test_now_before_the_last_activity_counts_as_no_time_passed(kind: Kind, before: timedelta) -> None:
    assert state_after(kind, -before) == "open"


def test_each_kind_is_judged_by_its_own_timing() -> None:
    """At 50 s a command is idle while a chat and a brainstorm are open; at 5,000 s a command is closed and a chat
    idle."""
    assert {k: state_after(k, timedelta(seconds=50)) for k in KINDS} == {
        "command": "idle", "chat": "open", "brainstorm": "open"}
    assert {k: state_after(k, timedelta(seconds=5_000)) for k in KINDS} == {
        "command": "closed", "chat": "idle", "brainstorm": "open"}


def test_fractional_thresholds_are_exact() -> None:
    p = Policy({k: Timing(idle_after_s=0.5, closed_after_s=2.25) for k in KINDS})
    assert state_after("chat", timedelta(milliseconds=500) - US, p) == "open"
    assert state_after("chat", timedelta(milliseconds=500), p) == "idle"
    assert state_after("chat", timedelta(milliseconds=2250) - US, p) == "idle"
    assert state_after("chat", timedelta(milliseconds=2250), p) == "closed"


def test_the_answer_depends_on_elapsed_time_not_on_the_date() -> None:
    later = T0 + timedelta(days=400, seconds=7)
    for kind in KINDS:
        idle = timedelta(seconds=POLICY.timings[kind].idle_after_s)
        assert POLICY.state_of(kind, later, later + idle) == state_after(kind, idle) == "idle"


ELAPSED = st.integers(min_value=-(10**13), max_value=10**13).map(lambda us: timedelta(microseconds=us))


@settings(max_examples=150, deadline=None)
@given(kind=st.sampled_from(KINDS), a=ELAPSED, b=ELAPSED)
def test_state_never_moves_backwards_as_time_passes(kind: Kind, a: timedelta, b: timedelta) -> None:
    early, late = sorted((a, b))
    assert RANK[state_after(kind, early)] <= RANK[state_after(kind, late)]


@settings(max_examples=150, deadline=None)
@given(kind=st.sampled_from(KINDS), elapsed=ELAPSED,
       idle_ms=st.integers(min_value=1, max_value=10**8), extra_ms=st.integers(min_value=1, max_value=10**8))
def test_state_is_the_documented_piecewise_function(kind: Kind, elapsed: timedelta, idle_ms: int,
                                                    extra_ms: int) -> None:
    idle, closed = idle_ms / 1000, (idle_ms + extra_ms) / 1000
    p = Policy({k: Timing(idle_after_s=idle, closed_after_s=closed) for k in KINDS})
    seconds = max(elapsed, timedelta(0))
    expected: State = ("open" if seconds < timedelta(milliseconds=idle_ms)
                       else "idle" if seconds < timedelta(milliseconds=idle_ms + extra_ms) else "closed")
    assert state_after(kind, elapsed, p) == expected


# --- parse ------------------------------------------------------------------------------------------------------

VALID: dict[str, Any] = {
    "command": {"idle_after_s": 10, "closed_after_s": 100},
    "chat": {"idle_after_s": 1_000, "closed_after_s": 10_000},
    "brainstorm": {"idle_after_s": 100_000, "closed_after_s": 1_000_000},
}


def test_parse_reads_every_kind_s_timing() -> None:
    assert parse(copy.deepcopy(VALID)) == POLICY


def test_parse_takes_fractional_seconds() -> None:
    data = copy.deepcopy(VALID)
    data["chat"] = {"idle_after_s": 0.5, "closed_after_s": 2.25}
    assert parse(data).timings["chat"] == Timing(idle_after_s=0.5, closed_after_s=2.25)


@pytest.mark.parametrize("data", [None, [], "policy", 3, [VALID]])
def test_parse_refuses_anything_but_an_object(data: object) -> None:
    with pytest.raises(ValueError):
        parse(data)


@pytest.mark.parametrize("kind", KINDS)
def test_parse_refuses_a_missing_kind_and_names_it(kind: str) -> None:
    data = copy.deepcopy(VALID)
    del data[kind]
    with pytest.raises(ValueError, match=kind):
        parse(data)


def test_parse_refuses_a_kind_that_does_not_exist_and_names_it() -> None:
    data = copy.deepcopy(VALID)
    data["smalltalk"] = {"idle_after_s": 1, "closed_after_s": 2}
    with pytest.raises(ValueError, match="smalltalk"):
        parse(data)


@pytest.mark.parametrize("field", ["idle_after_s", "closed_after_s"])
def test_parse_refuses_a_missing_threshold_and_names_it(field: str) -> None:
    data = copy.deepcopy(VALID)
    del data["chat"][field]
    with pytest.raises(ValueError, match=field):
        parse(data)


@pytest.mark.parametrize("timing", [
    {"idle_after_s": 0, "closed_after_s": 10},
    {"idle_after_s": -1, "closed_after_s": 10},
    {"idle_after_s": 10, "closed_after_s": 10},
    {"idle_after_s": 11, "closed_after_s": 10},
    {"idle_after_s": -10, "closed_after_s": -1},
    {"idle_after_s": "10", "closed_after_s": 100},
    {"idle_after_s": True, "closed_after_s": 100},
    {"idle_after_s": 10, "closed_after_s": None},
    {"idle_after_s": [10], "closed_after_s": 100},
    [10, 100],
    None,
    "10/100",
])
def test_parse_refuses_a_timing_that_breaks_the_rule(timing: object) -> None:
    data = copy.deepcopy(VALID)
    data["brainstorm"] = timing
    with pytest.raises(ValueError):
        parse(data)


@pytest.mark.parametrize("kind", KINDS)
def test_parse_refuses_a_bad_timing_whichever_kind_holds_it(kind: str) -> None:
    data = copy.deepcopy(VALID)
    data[kind] = {"idle_after_s": 5, "closed_after_s": 5}
    with pytest.raises(ValueError):
        parse(data)


# --- load -------------------------------------------------------------------------------------------------------


def test_load_gives_every_kind_a_valid_timing() -> None:
    shipped = load()
    assert set(shipped.timings) == set(KINDS)
    for t in shipped.timings.values():
        assert 0 < t.idle_after_s < t.closed_after_s


def test_load_is_the_policy_json_beside_the_module() -> None:
    path = Path(policy_module.__file__).parent / "policy.json"
    assert load() == parse(json.loads(path.read_text()))


def test_the_shipped_policy_answers_every_state_for_every_kind() -> None:
    shipped = load()
    for kind in KINDS:
        t = shipped.timings[kind]
        assert [state_after(kind, timedelta(seconds=s), shipped)
                for s in (0, t.idle_after_s, t.closed_after_s)] == ["open", "idle", "closed"]
