"""`ACTIVE_SITE_KEY`, `ACTIVE_SITE_MEMBER` and `FAILBACK`: the defaults are the Spilo layout, and `FAILBACK=off` leaves
fail-back out of the singletons while the others still run."""

import asyncio
from collections.abc import Generator

import pytest
from ashley import services, wiring_singletons
from ashley.db.database import Database
from ashley.referee.failback import NAME as FAILBACK
from ashley.referee.lease import Body, Lease
from ashley.settings import Settings, from_env

URL = "postgresql://nobody@127.0.0.1:1/none"
ETCD = {"ETCD_URL": "http://127.0.0.1:1", "SITE": "willow"}


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


def settings(**env: str) -> Settings:
    return from_env({"DATABASE_URL": URL, **env})


def started(config: Settings) -> list[str]:
    lease = RecordingLease()
    services.register(Lease, lease)

    async def go() -> None:
        await asyncio.gather(*wiring_singletons.singletons(config))

    asyncio.run(go())
    return lease.names


@pytest.mark.xfail(strict=True, reason="settings do not carry the leader key yet")
def test_the_defaults_are_the_spilo_leader_key_and_this_sites_member() -> None:
    config = settings(**ETCD)
    assert (config.active_site_key, config.active_site_member) == ("/service/postgres/leader", "willow")


@pytest.mark.xfail(strict=True, reason="settings do not carry the leader key yet")
def test_the_key_and_member_come_from_the_environment() -> None:
    config = settings(**ETCD, ACTIVE_SITE_KEY="/multisite/ashley/pg/leader", ACTIVE_SITE_MEMBER="asgard-pg")
    assert (config.active_site_key, config.active_site_member) == ("/multisite/ashley/pg/leader", "asgard-pg")
    assert config.site == "willow"


@pytest.mark.xfail(strict=True, reason="FAILBACK is not read yet")
def test_failback_off_leaves_fail_back_out_and_keeps_the_others() -> None:
    on = started(settings(**ETCD))
    off = started(settings(**ETCD, FAILBACK="off"))
    assert FAILBACK in on and FAILBACK not in off
    assert sorted(off) == sorted(n for n in on if n != FAILBACK)


def test_failback_on_is_the_default_and_spelled_on() -> None:
    assert sorted(started(settings(**ETCD, FAILBACK="on"))) == sorted(started(settings(**ETCD)))


@pytest.mark.xfail(strict=True, reason="FAILBACK is not validated yet")
@pytest.mark.parametrize("value", ["", "OFF", "no", "false", "0"])
def test_any_other_failback_value_is_refused_naming_it(value: str) -> None:
    with pytest.raises(ValueError, match="FAILBACK"):
        settings(**ETCD, FAILBACK=value)
