"""What the referee reads from Patroni and the one thing it asks Patroni to do. Patroni keeps its state in the same
etcd under `<namespace><scope>/` (live: `/service/postgres/`); this module names that layout's types, and
`patroni_etcd` reads them."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Member:
    """One Patroni member, from its `members/<name>` key (JSON written by Patroni every loop).

    `role` and `state` are Patroni's strings (`primary`/`replica`, `running`/`starting`/...). `wal` is the position in
    bytes this member has reached: `xlog_location` on a primary, `replay_lsn` on a replica; None when Patroni did not
    report it. `replication_state` is `streaming` while a replica follows the primary; None on a primary. `api_url`
    is its REST API (`http://<ip>:8008/patroni`)."""

    name: str
    role: str
    state: str
    timeline: int | None
    wal: int | None
    replication_state: str | None
    api_url: str


@dataclass(frozen=True)
class Promotion:
    """One entry of Patroni's `history` key: the moment `timeline` began and which member it began on (`None` in
    entries written before Patroni recorded it; `at` is `datetime.min` in UTC where no moment was recorded)."""

    timeline: int
    at: datetime
    new_leader: str | None


@dataclass(frozen=True)
class ClusterView:
    """Patroni's state as read in one etcd revision. `leader` is the `leader` key's value, None while there is none.
    `history` is oldest first."""

    leader: str | None
    members: dict[str, Member]
    history: tuple[Promotion, ...]

    def lag(self, name: str) -> int | None:
        """Bytes member `name` is behind the leader, or None when either position is unknown or there is no leader."""
        if self.leader is None or self.leader not in self.members or name not in self.members:
            return None
        lead, member = self.members[self.leader].wal, self.members[name].wal
        return None if lead is None or member is None else max(0, lead - member)


class PatroniUnavailable(Exception):
    """Patroni's state could not be read (etcd unreachable) or its reply was not understood."""


class Patroni(ABC):
    @abstractmethod
    async def view(self) -> ClusterView:
        """The cluster as Patroni last wrote it. Raises `PatroniUnavailable` and nothing else."""

    @abstractmethod
    async def switchover(self, leader: str, candidate: str) -> bool:
        """Ask `leader`'s REST API (its member key's `api_url`) to hand the primary to `candidate`
        (`POST /switchover`). True when Patroni answered that it switched over; False on any refusal or failure, which
        is logged. Never raises."""
