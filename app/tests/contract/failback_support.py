"""Builders for the fail-back contract tests: cluster views, a policy and a scripted Patroni."""

from datetime import UTC, datetime, timedelta

from ashley.referee.failback_policy import Policy
from ashley.referee.hold import Hold
from ashley.referee.patroni import ClusterView, Member, Patroni, PatroniUnavailable, Promotion

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
PREFERRED = "willow"
OTHER = "birch"
WAL = 1_000_000

POLICY = Policy(preferred=PREFERRED, poll_s=10, settle_s=300, max_settle_s=3600, max_lag_bytes=1000, window_s=21600)


def member(name: str, role: str = "replica", state: str = "running", timeline: int | None = 8, wal: int | None = WAL,
           replication_state: str | None = "streaming") -> Member:
    return Member(name, role, state, timeline, wal, replication_state, f"http://10.0.0.{len(name)}:8008/patroni")


def healthy_view(lag: int = 0, history: tuple[Promotion, ...] = (), leader: str = OTHER) -> ClusterView:
    """`leader` leads; the preferred member is a streaming replica on its timeline, `lag` bytes behind."""
    return ClusterView(
        leader,
        {leader: member(leader, "primary", replication_state=None), PREFERRED: member(PREFERRED, wal=WAL - lag)},
        history,
    )


def promotions_away(count: int, now: datetime = NOW, ago_s: float = 60) -> tuple[Promotion, ...]:
    """`count` promotions to a member other than the preferred one, each `ago_s` seconds before `now` (oldest first)."""
    return tuple(Promotion(10 + i, now - timedelta(seconds=ago_s * (count - i)), OTHER) for i in range(count))


class ScriptedPatroni(Patroni):
    """Answers `script` one entry per `view()` call (a view or a PatroniUnavailable), the last entry forever. Every
    call advances `ticks`; the test's clock is a function of it."""

    def __init__(self, script: list[ClusterView | PatroniUnavailable], answer: bool = True) -> None:
        self.script, self.answer = script, answer
        self.ticks = 0
        self.switchovers: list[tuple[str, str]] = []
        self.switchover_ticks: list[int] = []

    async def view(self) -> ClusterView:
        entry = self.script[min(self.ticks, len(self.script) - 1)]
        self.ticks += 1
        if isinstance(entry, PatroniUnavailable):
            raise entry
        return entry

    async def switchover(self, leader: str, candidate: str) -> bool:
        self.switchovers.append((leader, candidate))
        self.switchover_ticks.append(self.ticks)
        return self.answer

    def clock(self) -> datetime:
        """Ten seconds per `view()` call, on a fixed epoch."""
        return NOW + timedelta(seconds=10 * self.ticks)


class NoHold(Hold):
    """The maintenance switch, never set."""

    async def held(self) -> bool:
        return False
