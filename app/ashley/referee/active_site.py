"""Which site is active: the one whose Patroni member holds the database leader key in the referee's etcd
(`docs/decisions.md`, "Active site"). Singletons run only there, so they follow the writable database."""

from dataclasses import dataclass

PATRONI_LEADER_KEY = "/service/postgres/leader"


@dataclass(frozen=True)
class ActiveSite:
    """This site is active while etcd's `key` exists and its value is exactly `member`. Patroni writes its leader's
    member name there under a lease, so an absent key (an election in progress) means no site is active."""

    member: str
    key: str = PATRONI_LEADER_KEY
