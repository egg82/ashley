"""The fail-back singleton: after a failover, hand the primary back to the preferred site once it has streamed with no
lag for the wait `failback_policy` sets (`docs/decisions.md`, "One Postgres, managed by Patroni"). It runs under the
lease, so only on the active site, which is the one a fail-back moves the primary away from."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime

from .. import logs
from .failback_policy import Decision, Policy, step
from .hold import Hold
from .patroni import Patroni, PatroniUnavailable

log = logging.getLogger("ashley.referee.failback")

NAME = "fail-back"


class FailBack:
    """`run` is the lease body: it looks every `policy.poll_s` until cancelled, deciding each look with
    `failback_policy.step` and carrying `healthy_since` from one look to the next. A look that decides `switchover`
    calls `patroni.switchover(leader, policy.preferred)` once, and the health clock starts again whatever it answers.
    A look that raises `PatroniUnavailable` counts as unhealthy. Every look also asks `hold.held()` and passes it to
    `step`, so a look while the maintenance switch is set decides `wait` with reason `held`. The clock lives only in this tenure; a new holder
    starts it afresh, which can only delay a fail-back, never hasten one.

    Logs `failback.policy` with every threshold when it starts; `failback.state` (`reason`, `action`, `leader`, `lag`,
    `settle_s`) each time the reason differs from the previous look's; `failback.switchover` before asking and
    `failback.switchover_failed` when Patroni refuses; `failback.unavailable` once per run of unreadable looks."""

    def __init__(self, patroni: Patroni, hold: Hold, policy: Policy,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._patroni = patroni
        self._hold = hold
        self._policy = policy
        self._now = now

    async def run(self) -> None:
        logs.info(log, "failback.policy", **asdict(self._policy))
        healthy_since: datetime | None = None
        last = ""
        while True:
            healthy_since, last = await self._look(healthy_since, last)
            await asyncio.sleep(self._policy.poll_s)

    async def _look(self, healthy_since: datetime | None, last: str) -> tuple[datetime | None, str]:
        """One look; the health clock and the last logged reason to carry into the next."""
        try:
            view = await self._patroni.view()
        except PatroniUnavailable as e:
            if last != "unavailable":
                logs.warning(log, "failback.unavailable", error=str(e))
            return None, "unavailable"
        decision = step(view, self._now(), healthy_since, self._policy, held=await self._hold.held())
        if decision.reason != last:
            _log_decision(decision, view.leader, view.lag(self._policy.preferred))
        if decision.action != "switchover" or view.leader is None:
            return decision.healthy_since, decision.reason
        logs.info(log, "failback.switchover", leader=view.leader, candidate=self._policy.preferred,
                  lag=view.lag(self._policy.preferred), settle_s=decision.settle_s)
        if not await self._patroni.switchover(view.leader, self._policy.preferred):
            logs.warning(log, "failback.switchover_failed", leader=view.leader, candidate=self._policy.preferred)
        return None, "switchover"


def _log_decision(decision: Decision, leader: str | None, lag: int | None) -> None:
    logs.info(log, "failback.state", reason=decision.reason, action=decision.action, leader=leader, lag=lag,
              settle_s=decision.settle_s)
