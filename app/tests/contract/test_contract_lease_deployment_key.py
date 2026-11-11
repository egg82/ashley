"""The wired etcd lease follows the deployment's `ACTIVE_SITE_LEADER_PATH` and `ACTIVE_SITE_MEMBER`, against a real etcd."""

import asyncio
import uuid
from collections.abc import Generator

import pytest
from ashley import services
from ashley.referee.lease import Lease
from ashley.settings import from_env
from ashley.wiring_singletons import wire_lease
from etcd import etcd_url
from lease_support import Arena, campaign, delete, holder_of, put, run, unique_name

MEMBER = "asgard-pg"


@pytest.fixture(autouse=True)
def clean() -> Generator[None]:
    yield
    services.unregister(Lease)


def wired(key: str) -> Lease:
    wire_lease(from_env({"DATABASE_URL": "postgresql://nobody@127.0.0.1:1/none", "ETCD_URL": etcd_url(), "SITE": "iss",
                         "ACTIVE_SITE_LEADER_PATH": key, "ACTIVE_SITE_MEMBER": MEMBER}))
    return services.get(Lease)


def key_for(value: str | None) -> str:
    key = f"/ashley-test/deployment-{uuid.uuid4().hex[:12]}/leader"
    if value is None:
        delete(key)
    else:
        put(key, value)
    return key


def test_the_site_is_active_while_the_key_holds_its_member() -> None:
    name, arena, key = unique_name(), Arena(), key_for(MEMBER)

    async def scenario() -> None:
        async with campaign(wired(key), name, arena.body("a")):
            await asyncio.sleep(0.8)
            assert holder_of(name) is not None
        assert arena.starts

    run(scenario())


@pytest.mark.parametrize("value", ["iss-pg", None])
def test_the_site_is_inactive_for_another_member_or_an_absent_key(value: str | None) -> None:
    name, arena, key = unique_name(), Arena(), key_for(value)

    async def scenario() -> None:
        async with campaign(wired(key), name, arena.body("a")):
            await asyncio.sleep(0.8)
            assert holder_of(name) is None
        assert arena.starts == []

    run(scenario())
