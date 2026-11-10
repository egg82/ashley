"""The maintenance switch in fail-back: `failback_policy.step(held=...)` and the `FailBack` loop that asks a `Hold`
every look."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta

import pytest
from ashley import logs
from ashley.referee.failback import FailBack
from ashley.referee.failback_policy import Policy, settle_for, step
from ashley.referee.hold import Hold
from failback_support import NOW, OTHER, POLICY, PREFERRED, ScriptedPatroni, healthy_view, member, promotions_away
from lease_support import events, run, wait_until

LOOP_POLICY = Policy(preferred=PREFERRED, poll_s=0.001, settle_s=25, max_settle_s=100, max_lag_bytes=1000,
                     window_s=3600)


# --- step ------------------------------------------------------------------------------------------------------------

def test_held_defaults_to_false() -> None:
    since = NOW - timedelta(seconds=1000)
    assert step(healthy_view(), NOW, since, POLICY) == step(healthy_view(), NOW, since, POLICY, held=False)
    assert step(healthy_view(), NOW, since, POLICY).action == "switchover"


def test_a_healthy_replica_settled_long_ago_waits_while_held() -> None:
    since = NOW - timedelta(seconds=100_000)
    assert step(healthy_view(), NOW, since, POLICY, held=False).action == "switchover"
    decision = step(healthy_view(), NOW, since, POLICY, held=True)
    assert (decision.action, decision.reason) == ("wait", "held")


def test_the_wait_in_force_is_reported_while_held() -> None:
    view = healthy_view(history=promotions_away(3, NOW))
    decision = step(view, NOW, None, POLICY, held=True)
    assert decision.settle_s == settle_for(view, NOW, POLICY)


@pytest.mark.parametrize("held", [True, False])
def test_held_changes_nothing_while_the_preferred_member_leads(held: bool) -> None:
    view = healthy_view(leader=PREFERRED)
    decision = step(view, NOW, None, POLICY, held=held)
    assert (decision.action, decision.reason) == ("none", "preferred_leads")
    assert decision == step(view, NOW, None, POLICY, held=False)


def test_a_held_look_never_switches_over_whatever_the_state_of_the_cluster() -> None:
    lagging = healthy_view(lag=5000)
    gone = healthy_view()
    gone.members.pop(PREFERRED)
    broken = healthy_view()
    broken.members[PREFERRED] = member(PREFERRED, state="crashed")
    for view in (healthy_view(), lagging, gone, broken):
        assert step(view, NOW, NOW - timedelta(days=1), POLICY, held=True).action == "wait"


def test_health_counts_again_from_after_the_hold() -> None:
    first = step(healthy_view(), NOW, None, POLICY)
    assert first.healthy_since == NOW and first.reason == "settling"
    during = step(healthy_view(), NOW + timedelta(seconds=1000), first.healthy_since, POLICY, held=True)
    resumed_at = NOW + timedelta(seconds=1010)
    after = step(healthy_view(), resumed_at, during.healthy_since, POLICY)
    assert (after.action, after.reason) == ("wait", "settling")
    assert after.healthy_since == resumed_at
    later = step(healthy_view(), resumed_at + timedelta(seconds=POLICY.settle_s), after.healthy_since, POLICY)
    assert later.action == "switchover"


def test_a_long_hold_does_not_bank_health_from_before_it() -> None:
    since = NOW
    held_at = NOW + timedelta(seconds=POLICY.settle_s * 10)
    held = step(healthy_view(), held_at, since, POLICY, held=True)
    free = step(healthy_view(), held_at + timedelta(seconds=10), held.healthy_since, POLICY)
    assert free.action != "switchover"


# --- the loop --------------------------------------------------------------------------------------------------------

class ScriptedHold(Hold):
    """Answers `script` one entry per `held()` call, the last entry forever, noting the patroni tick of each ask."""

    def __init__(self, patroni: ScriptedPatroni, script: list[bool]) -> None:
        self.patroni, self.script = patroni, script
        self.asks: list[tuple[int, bool]] = []

    async def held(self) -> bool:
        answer = self.script[min(len(self.asks), len(self.script) - 1)]
        self.asks.append((self.patroni.ticks, answer))
        return answer

    def first_free_ask_after_last_hold(self) -> int:
        """The patroni tick at the first unheld ask that follows the final held ask."""
        last_held = max((i for i, (_, held) in enumerate(self.asks) if held), default=-1)
        return self.asks[last_held + 1][0]


async def drive(patroni: ScriptedPatroni, hold: Hold, until: Callable[[], object]) -> None:
    task = asyncio.create_task(FailBack(patroni, hold, LOOP_POLICY, now=patroni.clock).run())
    try:
        await wait_until(until, timeout=8)
        assert not task.done()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_a_hold_in_force_forever_never_switches_over() -> None:
    patroni = ScriptedPatroni([healthy_view()])
    hold = ScriptedHold(patroni, [True])
    run(drive(patroni, hold, lambda: patroni.ticks >= 25))
    assert patroni.switchovers == []


def test_every_look_asks_the_hold() -> None:
    patroni = ScriptedPatroni([healthy_view()])
    hold = ScriptedHold(patroni, [True])
    run(drive(patroni, hold, lambda: patroni.ticks >= 12))
    assert len(hold.asks) >= patroni.ticks - 1


def test_the_hold_is_asked_even_when_the_preferred_member_leads() -> None:
    patroni = ScriptedPatroni([healthy_view(leader=PREFERRED)])
    hold = ScriptedHold(patroni, [False])
    run(drive(patroni, hold, lambda: patroni.ticks >= 8))
    assert len(hold.asks) >= patroni.ticks - 1


def test_a_hold_that_arrives_late_stops_a_switchover_that_was_coming() -> None:
    patroni = ScriptedPatroni([healthy_view()])
    hold = ScriptedHold(patroni, [False, True])
    run(drive(patroni, hold, lambda: patroni.ticks >= 25))
    assert patroni.switchovers == []


def test_nothing_changes_without_a_hold_the_switchover_still_comes() -> None:
    patroni = ScriptedPatroni([healthy_view()])
    hold = ScriptedHold(patroni, [False])
    run(drive(patroni, hold, lambda: patroni.switchovers))
    assert patroni.switchovers[0] == (OTHER, PREFERRED)
    assert patroni.switchover_ticks[0] == 4


@pytest.mark.parametrize("held_looks", [3, 12])
def test_the_settle_wait_counts_from_after_the_release(held_looks: int) -> None:
    """Un-held, a healthy replica is switched to on the 4th look (25 s of 10 s looks). After a hold it needs three
    more looks past its first free one, however long the hold lasted."""
    patroni = ScriptedPatroni([healthy_view()])
    hold = ScriptedHold(patroni, [True] * held_looks + [False])
    run(drive(patroni, hold, lambda: patroni.switchovers))
    freed = hold.first_free_ask_after_last_hold()
    assert freed >= held_looks - 1
    assert patroni.switchover_ticks[0] - freed >= 3


def test_a_second_hold_restarts_the_wait_again() -> None:
    patroni = ScriptedPatroni([healthy_view()])
    hold = ScriptedHold(patroni, [False, False, True, False])
    run(drive(patroni, hold, lambda: patroni.switchovers))
    assert patroni.switchover_ticks[0] - hold.first_free_ask_after_last_hold() >= 3


def test_held_is_logged_once_per_run_of_held_looks_and_the_release_is_logged(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = ScriptedPatroni([healthy_view()])
    hold = ScriptedHold(patroni, [True] * 6 + [False])
    run(drive(patroni, hold, lambda: patroni.switchovers))
    reasons = [ln["reason"] for ln in events(capsys.readouterr().out, "failback.state")]
    assert reasons[0] == "held" and reasons.count("held") == 1
    assert reasons[1] == "settling" and "settled" in reasons


def test_no_held_state_is_logged_without_a_hold(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = ScriptedPatroni([healthy_view()])
    run(drive(patroni, ScriptedHold(patroni, [False]), lambda: patroni.switchovers))
    reasons = [ln["reason"] for ln in events(capsys.readouterr().out, "failback.state")]
    assert "held" not in reasons


def test_a_preferred_leader_under_a_hold_is_logged_as_leading_not_held(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = ScriptedPatroni([healthy_view(leader=PREFERRED)])
    run(drive(patroni, ScriptedHold(patroni, [True]), lambda: patroni.ticks >= 8))
    reasons = [ln["reason"] for ln in events(capsys.readouterr().out, "failback.state")]
    assert reasons == ["preferred_leads"]
