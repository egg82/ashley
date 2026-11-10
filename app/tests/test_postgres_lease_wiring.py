"""Without ETCD_URL the wired `Lease` is the Postgres one and every singleton but fail-back runs under it; with ETCD_URL
the lease is etcd's and fail-back joins them."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services, wiring_singletons
from ashley.db.database import Database
from ashley.referee.etcd_lease import EtcdLease
from ashley.referee.failback import NAME as FAILBACK
from ashley.referee.lease import Body, Lease
from ashley.referee.postgres_lease import PostgresLease
from ashley.settings import Settings
from ashley.wiring import wire

URL = "postgresql://nobody@127.0.0.1:1/none"
ETCD = {"etcd_url": "http://127.0.0.1:1", "site": "willow"}


class RecordingLease(Lease):
    def __init__(self) -> None:
        self.names: list[str] = []

    async def run(self, name: str, body: Body) -> None:
        self.names.append(name)


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    yield
    for interface in (Lease, Database):
        services.unregister(interface)


@pytest.mark.parametrize(("extra", "kind"), [({}, PostgresLease), (ETCD, EtcdLease)])
def test_the_wired_lease_is_postgres_without_etcd_and_etcd_with_it(extra: dict[str, str], kind: type[Lease]) -> None:
    wire(Settings(database_url=URL, build_version="t", **extra))
    assert type(services.get(Lease)) is kind


def started(settings: Settings) -> list[str]:
    lease = RecordingLease()
    services.register(Lease, lease)

    async def go() -> None:
        await asyncio.gather(*wiring_singletons.singletons(settings))

    asyncio.run(go())
    return lease.names


def test_without_etcd_every_singleton_but_fail_back_runs() -> None:
    bare = started(Settings(database_url=URL, build_version="t"))
    full = started(Settings(database_url=URL, build_version="t", **ETCD))
    assert FAILBACK not in bare and FAILBACK in full
    assert sorted(full) == sorted([*bare, FAILBACK])
    assert len(bare) >= 8
