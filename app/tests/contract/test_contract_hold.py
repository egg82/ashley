"""EtcdHold contract against a real etcd: one key per test, set/replace/release, expiry with the lease (on the fake
etcd and the virtual clock), and an unreachable etcd (held reads as True, everything else raises)."""

import asyncio
import base64
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
import virtual_time
from ashley.referee.etcd_gateway import EtcdUnavailable
from ashley.referee.hold import EtcdHold, Hold
from etcd import etcd_url
from etcd_fake import FakeEtcd
from lease_support import delete, kv_at, revoke, run, unique_name

DEAD = "http://127.0.0.1:1"


@pytest.fixture
def key() -> Generator[str]:
    name = f"/ashley-test/hold/{unique_name()}"
    yield name
    delete(name)


def now() -> datetime:
    return datetime.now(UTC)


def test_an_etcd_hold_is_a_hold(key: str) -> None:
    assert isinstance(EtcdHold(etcd_url(), key=key), Hold)


def test_nothing_is_held_to_begin_with(key: str) -> None:
    hold = EtcdHold(etcd_url(), key=key)

    async def scenario() -> None:
        assert await hold.held() is False
        assert await hold.until() is None

    run(scenario())


def test_set_holds_until_now_plus_the_duration(key: str) -> None:
    hold = EtcdHold(etcd_url(), key=key)

    async def scenario() -> None:
        returned = await hold.set(timedelta(minutes=10))
        assert returned.tzinfo is not None
        assert abs((returned - now() - timedelta(minutes=10)).total_seconds()) < 5
        assert await hold.held() is True
        assert await hold.until() == returned

    run(scenario())


def test_until_agrees_between_instances_on_the_same_key(key: str) -> None:
    async def scenario() -> None:
        returned = await EtcdHold(etcd_url(), key=key).set(timedelta(minutes=5))
        other = EtcdHold(etcd_url(), key=key)
        assert await other.held() is True
        assert await other.until() == returned

    run(scenario())


def test_the_value_is_the_expiry_in_iso_8601_utc(key: str) -> None:
    async def scenario() -> None:
        returned = await EtcdHold(etcd_url(), key=key).set(timedelta(minutes=5))
        record = kv_at(key)
        assert record is not None
        stored = datetime.fromisoformat(base64.b64decode(record["value"]).decode())
        assert stored.utcoffset() == timedelta(0)
        assert stored == returned

    run(scenario())


def test_the_key_lives_under_a_lease(key: str) -> None:
    async def scenario() -> None:
        await EtcdHold(etcd_url(), key=key).set(timedelta(minutes=5))

    run(scenario())
    record = kv_at(key)
    assert record is not None and int(record.get("lease", 0)) != 0


def test_two_keys_are_two_independent_switches(key: str) -> None:
    other_key = key + "-other"
    first, second = EtcdHold(etcd_url(), key=key), EtcdHold(etcd_url(), key=other_key)

    async def scenario() -> None:
        try:
            await first.set(timedelta(minutes=5))
            assert await second.held() is False
        finally:
            delete(other_key)

    run(scenario())


def test_release_clears_a_hold_and_says_there_was_one(key: str) -> None:
    hold = EtcdHold(etcd_url(), key=key)

    async def scenario() -> None:
        await hold.set(timedelta(minutes=5))
        assert await hold.release() is True
        assert await hold.held() is False
        assert await hold.until() is None
        assert kv_at(key) is None

    run(scenario())


def test_releasing_twice_says_nothing_was_there_the_second_time(key: str) -> None:
    hold = EtcdHold(etcd_url(), key=key)

    async def scenario() -> None:
        await hold.set(timedelta(minutes=5))
        assert await hold.release() is True
        assert await hold.release() is False

    run(scenario())


def test_releasing_with_no_hold_is_false(key: str) -> None:
    run(_release_is_false(EtcdHold(etcd_url(), key=key)))


async def _release_is_false(hold: EtcdHold) -> None:
    assert await hold.release() is False


def test_a_second_set_replaces_the_first(key: str) -> None:
    hold = EtcdHold(etcd_url(), key=key)

    async def scenario() -> None:
        await hold.set(timedelta(hours=2))
        shorter = await hold.set(timedelta(minutes=10))
        assert await hold.until() == shorter
        assert abs((shorter - now() - timedelta(minutes=10)).total_seconds()) < 5
        longer = await hold.set(timedelta(hours=3))
        assert await hold.until() == longer

    run(scenario())


def test_a_replaced_hold_is_one_key_and_releases_once(key: str) -> None:
    hold = EtcdHold(etcd_url(), key=key)

    async def scenario() -> None:
        await hold.set(timedelta(minutes=5))
        await hold.set(timedelta(minutes=6))
        assert await hold.release() is True
        assert await hold.held() is False

    run(scenario())


def test_the_hold_goes_when_its_lease_is_revoked(key: str) -> None:
    hold = EtcdHold(etcd_url(), key=key)

    async def scenario() -> None:
        await hold.set(timedelta(hours=1))

    run(scenario())
    record = kv_at(key)
    assert record is not None
    revoke(str(record["lease"]))

    async def after() -> None:
        assert await hold.held() is False
        assert await hold.until() is None

    run(after())


def test_a_short_hold_expires_on_its_own() -> None:
    """On the fake etcd and the virtual clock."""
    etcd, key = FakeEtcd(), "/ashley-test/hold/short"
    hold = EtcdHold("", key=key, connect=etcd.connect())

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        await hold.set(timedelta(seconds=1))
        assert await hold.held() is True
        deadline = loop.time() + 20
        while await hold.held():
            assert loop.time() < deadline, "a one-second hold never expired"
            await asyncio.sleep(0.2)
        assert await hold.until() is None
        assert etcd.value(key) is None

    virtual_time.run(scenario())


def test_an_unreachable_etcd_reads_as_held() -> None:
    async def scenario() -> None:
        assert await EtcdHold(DEAD, timeout=1.0).held() is True

    run(scenario())


def test_an_unreachable_etcd_raises_from_everything_else() -> None:
    hold = EtcdHold(DEAD, timeout=1.0)

    async def scenario() -> None:
        with pytest.raises(EtcdUnavailable):
            await hold.until()
        with pytest.raises(EtcdUnavailable):
            await hold.set(timedelta(minutes=5))
        with pytest.raises(EtcdUnavailable):
            await hold.release()

    run(scenario())


def test_held_after_an_unreachable_failure_is_still_true_not_an_exception() -> None:
    hold = EtcdHold(DEAD, timeout=1.0)

    async def scenario() -> None:
        with pytest.raises(EtcdUnavailable):
            await hold.until()
        assert await hold.held() is True

    run(scenario())
