"""Fail-back policy contract: the shipped policy and the pure functions `settle_for`, `health` and `step`."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import ashley.referee
import pytest
from ashley.referee.failback_policy import Decision, Policy, health, load, settle_for, step
from ashley.referee.patroni import ClusterView, Promotion
from failback_support import NOW, OTHER, POLICY, PREFERRED, healthy_view, member, promotions_away
from hypothesis import given
from hypothesis import strategies as st


def test_load_reads_the_shipped_json() -> None:
    raw = json.loads((Path(ashley.referee.__file__).parent / "failback.json").read_text())
    policy = load()
    assert policy == Policy(**raw)
    assert policy.preferred and policy.poll_s > 0 and policy.settle_s > 0
    assert policy.settle_s <= policy.max_settle_s and policy.max_lag_bytes >= 0 and policy.window_s > 0


# --- health ----------------------------------------------------------------------------------------------------------

def test_a_streaming_caught_up_replica_on_the_leaders_timeline_is_healthy() -> None:
    assert health(healthy_view(), POLICY) is None


def test_the_preferred_member_missing() -> None:
    view = ClusterView(OTHER, {OTHER: member(OTHER, "primary", replication_state=None)}, ())
    assert health(view, POLICY) == "missing"


@pytest.mark.parametrize("state", ["starting", "stopped", "crashed", "restarting"])
def test_not_running(state: str) -> None:
    view = healthy_view()
    view.members[PREFERRED] = member(PREFERRED, state=state)
    assert health(view, POLICY) == "not_running"


def test_not_a_replica() -> None:
    view = healthy_view()
    view.members[PREFERRED] = member(PREFERRED, role="primary", replication_state=None)
    assert health(view, POLICY) == "not_replica"


@pytest.mark.parametrize("state", ["catchup", "stopped", None])
def test_not_streaming(state: str | None) -> None:
    view = healthy_view()
    view.members[PREFERRED] = member(PREFERRED, replication_state=state)
    assert health(view, POLICY) == "not_streaming"


@pytest.mark.parametrize("timeline", [7, 9])
def test_on_another_timeline(timeline: int) -> None:
    view = healthy_view()
    view.members[PREFERRED] = member(PREFERRED, timeline=timeline)
    assert health(view, POLICY) == "other_timeline"


def test_lag_unknown_when_the_preferred_position_is_unreported() -> None:
    view = healthy_view()
    view.members[PREFERRED] = member(PREFERRED, wal=None)
    assert health(view, POLICY) == "lag_unknown"


def test_lag_unknown_when_the_leaders_position_is_unreported() -> None:
    view = healthy_view()
    view.members[OTHER] = member(OTHER, "primary", wal=None, replication_state=None)
    assert health(view, POLICY) == "lag_unknown"


def test_lag_is_judged_at_most_the_limit() -> None:
    assert health(healthy_view(lag=POLICY.max_lag_bytes), POLICY) is None
    assert health(healthy_view(lag=POLICY.max_lag_bytes + 1), POLICY) == "lagging"


@given(lag=st.integers(0, 10_000), limit=st.integers(0, 10_000))
def test_lagging_exactly_when_over_the_limit(lag: int, limit: int) -> None:
    result = health(healthy_view(lag=lag), replace(POLICY, max_lag_bytes=limit))
    assert result == (None if lag <= limit else "lagging")


# --- settle_for ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("away,expected", [(0, 300), (1, 300), (2, 600), (3, 1200), (4, 2400), (5, 3600), (6, 3600), (200, 3600)])
def test_each_promotion_away_beyond_the_first_doubles_the_wait_up_to_the_cap(away: int, expected: float) -> None:
    assert settle_for(healthy_view(history=promotions_away(away)), NOW, POLICY) == expected


def test_promotions_older_than_the_window_do_not_count() -> None:
    old = promotions_away(5, ago_s=30_000)
    recent = promotions_away(2, ago_s=60)
    assert settle_for(healthy_view(history=old + recent), NOW, POLICY) == 600
    assert settle_for(healthy_view(history=old), NOW, POLICY) == 300


def test_promotions_to_the_preferred_member_do_not_count() -> None:
    back = tuple(Promotion(20 + i, NOW - timedelta(seconds=30 * (5 - i)), PREFERRED) for i in range(5))
    assert settle_for(healthy_view(history=back + promotions_away(2)), NOW, POLICY) == 600


@given(n=st.integers(0, 12), settle=st.integers(1, 500), cap_factor=st.integers(1, 20))
def test_the_wait_stays_between_settle_and_the_cap_and_never_shrinks_with_more_promotions(n: int, settle: int, cap_factor: int) -> None:
    policy = replace(POLICY, settle_s=settle, max_settle_s=settle * cap_factor)
    now = NOW
    waits = [settle_for(healthy_view(history=promotions_away(k, now)), now, policy) for k in range(n + 1)]
    assert all(settle <= w <= settle * cap_factor for w in waits)
    assert waits == sorted(waits)


# --- step ------------------------------------------------------------------------------------------------------------

def test_nothing_to_do_while_the_preferred_member_leads() -> None:
    view = healthy_view(leader=PREFERRED)
    for carried in (None, NOW - timedelta(hours=1)):
        decision = step(view, NOW, carried, POLICY)
        assert (decision.action, decision.reason, decision.healthy_since) == ("none", "preferred_leads", None)
        assert decision.settle_s == POLICY.settle_s


def test_no_leader_never_switches_over_and_clears_the_clock() -> None:
    view = ClusterView(None, healthy_view().members, ())
    decision = step(view, NOW, NOW - timedelta(hours=1), POLICY)
    assert decision.reason == "no_leader"
    assert decision.action != "switchover"
    assert decision.healthy_since is None


def test_an_unhealthy_look_names_the_failure_and_restarts_the_clock() -> None:
    view = healthy_view(lag=POLICY.max_lag_bytes + 5)
    decision = step(view, NOW, NOW - timedelta(hours=1), POLICY)
    assert decision.reason == "lagging" == health(view, POLICY)
    assert decision.action != "switchover"
    assert decision.healthy_since is None


def test_the_first_healthy_look_starts_the_clock_and_waits() -> None:
    decision = step(healthy_view(), NOW, None, POLICY)
    assert (decision.action, decision.reason, decision.healthy_since) == ("wait", "settling", NOW)
    assert decision.settle_s == POLICY.settle_s


def test_a_healthy_look_inside_the_wait_keeps_the_clock() -> None:
    since = NOW - timedelta(seconds=POLICY.settle_s - 1)
    decision = step(healthy_view(), NOW, since, POLICY)
    assert (decision.action, decision.reason, decision.healthy_since) == ("wait", "settling", since)


def test_a_healthy_look_past_the_wait_switches_over() -> None:
    since = NOW - timedelta(seconds=POLICY.settle_s + 1)
    decision = step(healthy_view(), NOW, since, POLICY)
    assert (decision.action, decision.reason) == ("switchover", "settled")
    assert decision.settle_s == POLICY.settle_s


def test_the_wait_in_force_is_the_lengthened_one() -> None:
    view = healthy_view(history=promotions_away(3))
    assert settle_for(view, NOW, POLICY) == 1200
    waiting = step(view, NOW, NOW - timedelta(seconds=600), POLICY)
    assert (waiting.action, waiting.reason, waiting.settle_s) == ("wait", "settling", 1200)
    done = step(view, NOW, NOW - timedelta(seconds=1300), POLICY)
    assert (done.action, done.reason, done.settle_s) == ("switchover", "settled", 1200)


Look = tuple[str, int]


@st.composite
def looks(draw: st.DrawFn) -> list[Look]:
    kinds = st.sampled_from(["healthy", "healthy", "healthy", "lagging", "no_leader", "preferred_leads"])
    return draw(st.lists(st.tuples(kinds, st.integers(1, 400)), min_size=1, max_size=40))


def view_for(kind: str) -> ClusterView:
    if kind == "no_leader":
        return ClusterView(None, healthy_view().members, ())
    if kind == "preferred_leads":
        return healthy_view(leader=PREFERRED)
    return healthy_view(lag=0 if kind == "healthy" else POLICY.max_lag_bytes + 1)


@given(sequence=looks())
def test_a_switchover_only_ever_follows_an_unbroken_healthy_run_as_long_as_the_wait(sequence: list[Look]) -> None:
    now: datetime = NOW
    carried: datetime | None = None
    streak: datetime | None = None
    for kind, gap in sequence:
        now += timedelta(seconds=gap)
        decision: Decision = step(view_for(kind), now, carried, POLICY)
        streak = (streak or now) if kind == "healthy" else None
        if decision.action == "switchover":
            assert kind == "healthy"
            assert streak is not None and now - streak >= timedelta(seconds=POLICY.settle_s)
        if kind != "healthy":
            assert decision.healthy_since is None
            assert decision.action != "switchover"
        carried = None if decision.action == "switchover" else decision.healthy_since
        if decision.action == "switchover":
            streak = None


@given(since_s=st.integers(0, 2000))
def test_the_decision_is_a_pure_function_of_its_inputs(since_s: int) -> None:
    since = NOW - timedelta(seconds=since_s)
    view = healthy_view(history=promotions_away(2))
    assert step(view, NOW, since, POLICY) == step(view, NOW, since, POLICY)


def test_a_look_exactly_at_the_wait_switches_over() -> None:
    """Directed at a surviving mutant (`>` for `>=`): the docstring says at or past the wait."""
    decision = step(healthy_view(), NOW, NOW - timedelta(seconds=POLICY.settle_s), POLICY)
    assert decision.action == "switchover"
