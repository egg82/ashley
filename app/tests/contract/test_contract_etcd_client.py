"""EtcdClient contract, run against the real etcd and against `etcd_fake`: any way the fake answers differently from
etcd fails here. What it cannot hold the fake to within the time gate is when a lease expires on its own (etcd frees a
2 s lease about 2.3 s after granting it; the fake at exactly 2 s); the fake's side of that is the last test."""

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import pytest
import virtual_time
from ashley.referee.etcd_gateway import Connect, EtcdGateway, EtcdUnavailable
from etcd import etcd_url
from etcd_fake import FakeEtcd, Link
from lease_support import run as run_real

Scenario = Coroutine[Any, Any, None]


@dataclass
class Stand:
    connect: Connect
    unreachable: Connect
    run: Callable[[Scenario], None]
    root: str


@pytest.fixture(params=["real", "fake"])
def stand(request: pytest.FixtureRequest) -> Stand:
    root = f"/ashley-test/client-{uuid.uuid4().hex[:12]}/"
    if request.param == "real":
        url = etcd_url()
        return Stand(EtcdGateway.connect(url), EtcdGateway.connect("http://127.0.0.1:1"), run_real, root)
    fake = FakeEtcd()
    return Stand(fake.connect(), fake.connect(Link(down=True)), virtual_time.run, root)


def test_a_grant_gets_the_ttl_asked_for_and_never_less_than_two_seconds(stand: Stand) -> None:
    async def scenario() -> None:
        async with stand.connect(5.0) as etcd:
            assert (await etcd.grant(1)).ttl == 2
            assert (await etcd.grant(7)).ttl == 7

    stand.run(scenario())


def test_keepalive_answers_the_granted_ttl_and_zero_once_revoked(stand: Stand) -> None:
    async def scenario() -> None:
        async with stand.connect(5.0) as etcd:
            grant = await etcd.grant(5)
            assert await etcd.keepalive(grant.lease_id) == 5
            await etcd.revoke(grant.lease_id)
            assert await etcd.keepalive(grant.lease_id) == 0
            await etcd.revoke(grant.lease_id)

    stand.run(scenario())


def test_a_claim_takes_an_absent_key_once_and_again_after_it_is_deleted(stand: Stand) -> None:
    key = stand.root + "k"

    async def scenario() -> None:
        async with stand.connect(5.0) as etcd:
            first, second = (await etcd.grant(10)).lease_id, (await etcd.grant(10)).lease_id
            assert await etcd.claim(key, "a", first, None) is True
            assert await etcd.claim(key, "b", second, None) is False
            assert await etcd.get(key) == "a"
            assert await etcd.delete(key) is True
            assert await etcd.delete(key) is False
            assert await etcd.get(key) is None
            assert await etcd.claim(key, "b", second, None) is True
            assert await etcd.get(key) == "b"

    stand.run(scenario())


def test_a_guarded_claim_needs_the_guard_key_to_hold_exactly_the_value(stand: Stand) -> None:
    key, leader = stand.root + "k", stand.root + "leader"

    async def scenario() -> None:
        async with stand.connect(5.0) as etcd:
            lease = (await etcd.grant(10)).lease_id
            assert await etcd.claim(key, "a", lease, (leader, "a")) is False
            for wrong in ("ab", "", "A"):
                await etcd.put(leader, wrong, lease)
                assert await etcd.claim(key, "a", lease, (leader, "a")) is False
            assert await etcd.get(key) is None
            await etcd.put(leader, "a", lease)
            assert await etcd.claim(key, "a", lease, (leader, "a")) is True

    stand.run(scenario())


def test_revoking_a_lease_deletes_its_keys_and_only_its_keys(stand: Stand) -> None:
    mine, other = stand.root + "mine", stand.root + "other"

    async def scenario() -> None:
        async with stand.connect(5.0) as etcd:
            first, second = (await etcd.grant(10)).lease_id, (await etcd.grant(10)).lease_id
            assert await etcd.claim(mine, "a", first, None)
            await etcd.put(other, "b", second)
            await etcd.revoke(first)
            assert await etcd.get(mine) is None
            assert await etcd.get(other) == "b"

    stand.run(scenario())


def test_a_write_under_a_revoked_lease_raises_404_unless_the_claim_is_refused_first(stand: Stand) -> None:
    key, taken = stand.root + "k", stand.root + "taken"

    async def scenario() -> None:
        async with stand.connect(5.0) as etcd:
            live, gone = (await etcd.grant(10)).lease_id, (await etcd.grant(10)).lease_id
            await etcd.put(taken, "x", live)
            await etcd.revoke(gone)
            for write in (etcd.put(key, "a", gone), etcd.claim(key, "a", gone, None)):
                with pytest.raises(EtcdUnavailable) as raised:
                    await write
                assert raised.value.status == 404
            assert await etcd.claim(taken, "a", gone, None) is False
            assert await etcd.get(key) is None

    stand.run(scenario())


def test_put_replaces_and_prefix_reads_only_keys_under_the_prefix(stand: Stand) -> None:
    async def scenario() -> None:
        async with stand.connect(5.0) as etcd:
            lease = (await etcd.grant(10)).lease_id
            for key, value in (("p/a", "1"), ("p/b", "2"), ("pq", "3"), ("p/a", "4")):
                await etcd.put(stand.root + key, value, lease)
            assert await etcd.prefix(stand.root + "p/") == {stand.root + "p/a": "4", stand.root + "p/b": "2"}
            assert await etcd.prefix(stand.root + "p/a", exact=True) == {stand.root + "p/a": "4"}
            assert await etcd.prefix(stand.root + "p", exact=True) == {}

    stand.run(scenario())


def test_an_unreachable_etcd_raises_etcd_unavailable_naming_the_error_and_no_address(stand: Stand) -> None:
    async def scenario() -> None:
        async with stand.unreachable(1.0) as etcd:
            calls = (etcd.grant(5), etcd.keepalive(1), etcd.claim("k", "v", 1, None), etcd.put("k", "v", 1),
                     etcd.delete("k"), etcd.get("k"), etcd.revoke(1))
            for call in calls:
                with pytest.raises(EtcdUnavailable) as raised:
                    await call
                assert str(raised.value) == "ConnectError"

    stand.run(scenario())


def test_the_fake_frees_a_lease_once_its_ttl_runs_out_and_a_keepalive_restarts_it() -> None:
    fake = FakeEtcd()

    async def scenario() -> None:
        async with fake.connect()(5.0) as etcd:
            kept, left = (await etcd.grant(3)).lease_id, (await etcd.grant(3)).lease_id
            await etcd.put("kept", "a", kept)
            await etcd.put("left", "b", left)
            await asyncio.sleep(2.0)
            assert await etcd.keepalive(kept) == 3
            await asyncio.sleep(1.5)
            assert await etcd.get("left") is None
            assert await etcd.keepalive(left) == 0
            assert await etcd.get("kept") == "a"
            await asyncio.sleep(1.5)
            assert await etcd.get("kept") is None

    virtual_time.run(scenario())
