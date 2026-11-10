"""FailBack contract: the singleton's loop over a scripted Patroni, with a clock that moves ten seconds per look."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace

import pytest
from ashley import logs
from ashley.referee.failback import FailBack
from ashley.referee.failback_policy import Policy
from ashley.referee.patroni import ClusterView, PatroniUnavailable
from failback_support import OTHER, PREFERRED, NoHold, ScriptedPatroni, healthy_view, promotions_away
from lease_support import events, run, wait_until

POLICY = Policy(preferred=PREFERRED, poll_s=0.001, settle_s=25, max_settle_s=100, max_lag_bytes=1000, window_s=3600)
LAGGING = healthy_view(lag=2000)


async def drive(patroni: ScriptedPatroni, until: Callable[[], object], policy: Policy = POLICY) -> None:
    """Run FailBack against `patroni` until `until()`, then cancel it; its end must be the cancellation."""
    task = asyncio.create_task(FailBack(patroni, NoHold(), policy, now=patroni.clock).run())
    try:
        await wait_until(until, timeout=8)
        assert not task.done()
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def first_switchover_after(script: list[ClusterView | PatroniUnavailable], policy: Policy = POLICY) -> int:
    patroni = ScriptedPatroni(script)
    run(drive(patroni, lambda: patroni.switchovers, policy))
    return patroni.switchover_ticks[0]


def test_a_healthy_replica_is_handed_the_primary_once_it_has_settled() -> None:
    patroni = ScriptedPatroni([healthy_view()])
    run(drive(patroni, lambda: patroni.switchovers))
    assert patroni.switchovers[0] == (OTHER, PREFERRED)
    assert patroni.switchover_ticks[0] == 4


def test_the_switchover_names_the_current_leader() -> None:
    patroni = ScriptedPatroni([healthy_view(leader="third")])
    run(drive(patroni, lambda: patroni.switchovers))
    assert patroni.switchovers[0] == ("third", PREFERRED)


@pytest.mark.parametrize("answer", [True, False])
def test_the_health_clock_restarts_after_a_switchover_whatever_patroni_answers(answer: bool) -> None:
    patroni = ScriptedPatroni([healthy_view()], answer=answer)
    run(drive(patroni, lambda: len(patroni.switchovers) >= 3))
    ticks = patroni.switchover_ticks
    assert ticks[1] - ticks[0] >= 3 and ticks[2] - ticks[1] >= 3


def test_nothing_happens_while_the_preferred_member_leads() -> None:
    patroni = ScriptedPatroni([healthy_view(leader=PREFERRED)])
    run(drive(patroni, lambda: patroni.ticks >= 12))
    assert patroni.switchovers == []


def test_nothing_happens_while_the_replica_lags() -> None:
    patroni = ScriptedPatroni([LAGGING])
    run(drive(patroni, lambda: patroni.ticks >= 12))
    assert patroni.switchovers == []


def test_nothing_happens_while_there_is_no_leader() -> None:
    patroni = ScriptedPatroni([replace(healthy_view(), leader=None)])
    run(drive(patroni, lambda: patroni.ticks >= 12))
    assert patroni.switchovers == []


def test_one_unhealthy_look_restarts_the_wait() -> None:
    assert first_switchover_after([healthy_view(), healthy_view(), LAGGING, healthy_view()]) == 7


def test_an_unreadable_look_counts_as_unhealthy_and_does_not_end_the_loop() -> None:
    assert first_switchover_after([healthy_view(), healthy_view(), PatroniUnavailable("etcd"), healthy_view()]) == 7


def test_a_promotion_history_lengthens_the_wait() -> None:
    """Three promotions away make the wait 26 s * 4 = 104 s: not reached at 100 s, reached at 110 s."""
    slow = replace(POLICY, settle_s=26, max_settle_s=200)
    assert first_switchover_after([healthy_view(history=promotions_away(3))], slow) == 12


def test_cancelling_stops_the_loop() -> None:
    patroni = ScriptedPatroni([healthy_view(leader=PREFERRED)])

    async def scenario() -> None:
        task = asyncio.create_task(FailBack(patroni, NoHold(), POLICY, now=patroni.clock).run())
        await wait_until(lambda: patroni.ticks >= 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        ticks = patroni.ticks
        await asyncio.sleep(0.05)
        assert patroni.ticks == ticks

    run(scenario())


# --- logs ------------------------------------------------------------------------------------------------------------

def test_the_policy_is_logged_once_at_start(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = ScriptedPatroni([healthy_view(leader=PREFERRED)])
    run(drive(patroni, lambda: patroni.ticks >= 6))
    logged = events(capsys.readouterr().out, "failback.policy")
    assert len(logged) == 1
    line = logged[0]
    assert {"preferred", "poll_s", "settle_s", "max_settle_s", "max_lag_bytes", "window_s"} <= set(line)
    assert (line["preferred"], line["settle_s"], line["max_settle_s"], line["max_lag_bytes"]) == (PREFERRED, "25", "100", "1000")


def test_the_state_is_logged_only_when_the_reason_changes(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = ScriptedPatroni([healthy_view(lag=100)])
    run(drive(patroni, lambda: len(patroni.switchovers) >= 2))
    out = capsys.readouterr().out
    states = events(out, "failback.state")
    reasons = [ln["reason"] for ln in states]
    assert reasons[0] == "settling" and "settled" in reasons
    assert all(a != b for a, b in zip(reasons, reasons[1:], strict=False))
    assert len(states) < patroni.ticks
    first = states[0]
    assert (first["leader"], first["lag"]) == (OTHER, "100")
    assert {"action", "settle_s"} <= set(first)


def test_a_steady_preferred_leader_logs_its_state_once(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = ScriptedPatroni([healthy_view(leader=PREFERRED)])
    run(drive(patroni, lambda: patroni.ticks >= 10))
    states = events(capsys.readouterr().out, "failback.state")
    assert [ln["reason"] for ln in states] == ["preferred_leads"]


def test_unreadable_looks_are_logged_once_per_run(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    down = PatroniUnavailable("etcd")
    patroni = ScriptedPatroni([down, down, down, healthy_view(), healthy_view(), down, down, healthy_view()])
    run(drive(patroni, lambda: patroni.switchovers))
    assert len(events(capsys.readouterr().out, "failback.unavailable")) == 2


class Recording(ScriptedPatroni):
    """Captures what had been logged at the moment `switchover` was asked."""

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        super().__init__([healthy_view()])
        self.capsys, self.before = capsys, ""

    async def switchover(self, leader: str, candidate: str) -> bool:
        if not self.switchovers:
            self.before = self.capsys.readouterr().out
        return await super().switchover(leader, candidate)


def test_the_switchover_is_logged_before_patroni_is_asked(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = Recording(capsys)
    run(drive(patroni, lambda: patroni.switchovers))
    assert len(events(patroni.before, "failback.switchover")) == 1


@pytest.mark.parametrize("answer", [True, False])
def test_a_refused_switchover_is_logged_as_failed_and_an_accepted_one_is_not(
    answer: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    logs.setup()
    capsys.readouterr()
    patroni = ScriptedPatroni([healthy_view()], answer=answer)
    run(drive(patroni, lambda: len(patroni.switchovers) >= 2))
    out = capsys.readouterr().out
    assert len(events(out, "failback.switchover_failed")) >= (1 if not answer else 0)
    assert (events(out, "failback.switchover_failed") == []) is answer
