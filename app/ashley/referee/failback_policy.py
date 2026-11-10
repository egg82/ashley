"""When the fail-back singleton hands the primary back to the preferred site: a pure decision over one `ClusterView`,
so every threshold is data (`failback.json`) and every outcome is a function of what Patroni reported and the time."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import resources
from typing import Literal

from .patroni import ClusterView

Action = Literal["none", "wait", "switchover"]


@dataclass(frozen=True)
class Policy:
    """`preferred` is the member that should lead. `poll_s` is how often the singleton looks. The preferred member
    must be a streaming replica on the leader's timeline, at most `max_lag_bytes` behind, for `settle_s` without a
    break before it is handed the primary. Each promotion away from it in the last `window_s` (from Patroni's
    history) beyond the first doubles that wait, up to `max_settle_s`, so a site that keeps failing gets it back
    ever more slowly instead of ping-ponging."""

    preferred: str
    poll_s: float
    settle_s: float
    max_settle_s: float
    max_lag_bytes: int
    window_s: float


def load() -> Policy:
    """The policy shipped in `failback.json` beside this module."""
    data = json.loads(resources.files("ashley.referee").joinpath("failback.json").read_text())
    return Policy(**data)


@dataclass(frozen=True)
class Decision:
    """What to do now. `reason` names why: `preferred_leads`, `held`, `no_leader`, a health failure (`missing`,
    `not_running`, `not_replica`, `not_streaming`, `other_timeline`, `lag_unknown`, `lagging`), `settling` or
    `settled`. `healthy_since` is carried into the next call: the moment the preferred member's current unbroken run of
    health began, None when it is not healthy. `settle_s` is the wait in force."""

    action: Action
    reason: str
    healthy_since: datetime | None
    settle_s: float


def settle_for(view: ClusterView, now: datetime, policy: Policy) -> float:
    """The wait in force: `settle_s` doubled once per promotion away from the preferred member in the last
    `window_s` beyond the first, capped at `max_settle_s`."""
    since = now - timedelta(seconds=policy.window_s)
    away = sum(1 for p in view.history if p.at >= since and p.new_leader not in (None, policy.preferred))
    return min(policy.max_settle_s, policy.settle_s * 2 ** max(0, away - 1))


def health(view: ClusterView, policy: Policy) -> str | None:
    """Why the preferred member is not ready to lead, or None when it is. Assumes another member leads."""
    member = view.members.get(policy.preferred)
    leader = view.members.get(view.leader or "")
    if member is None:
        return "missing"
    if member.state != "running":
        return "not_running"
    if member.role != "replica":
        return "not_replica"
    if member.replication_state != "streaming":
        return "not_streaming"
    if leader is None or member.timeline is None or member.timeline != leader.timeline:
        return "other_timeline"
    lag = view.lag(policy.preferred)
    if lag is None:
        return "lag_unknown"
    return "lagging" if lag > policy.max_lag_bytes else None


def step(view: ClusterView, now: datetime, healthy_since: datetime | None, policy: Policy,
         held: bool = False) -> Decision:
    """One look. `healthy_since` is the previous Decision's (None on the first look of a tenure). Switch over only
    when another member leads and the preferred member has been healthy for the wait in force; any unhealthy look
    restarts that wait. Health counts from the first healthy look, and a look at or past the wait switches over;
    every look that does not is `wait`, except `none` while the preferred member leads. While `held` (the maintenance
    switch, `hold.Hold`) it waits with reason `held` and the clock stops: health counts again from after the hold."""
    settle = settle_for(view, now, policy)
    if view.leader == policy.preferred:
        return Decision("none", "preferred_leads", None, settle)
    if held:
        return Decision("wait", "held", None, settle)
    if view.leader is None:
        return Decision("wait", "no_leader", None, settle)
    problem = health(view, policy)
    if problem is not None:
        return Decision("wait", problem, None, settle)
    since = healthy_since or now
    if (now - since).total_seconds() >= settle:
        return Decision("switchover", "settled", since, settle)
    return Decision("wait", "settling", since, settle)
