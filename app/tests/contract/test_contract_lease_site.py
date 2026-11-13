"""Lease contract, active-site part: a process campaigns and holds only while its site's member leads the database. The
tests on `FakeStand` run on the fake etcd and the virtual clock; the rest against the real etcd."""

import asyncio
import uuid
from contextlib import AsyncExitStack

import httpx2
import pytest
from ashley import logs
from ashley.referee.active_site import ActiveSite
from ashley.referee.etcd_gateway import EtcdGateway
from ashley.referee.etcd_lease import EtcdLease
from etcd import etcd_url
from lease_support import Arena, FakeStand, campaign, delete, events, holder_of, put, run, unique_name, wait_until


def leader_key() -> str:
    return f"/ashley-test/site-{uuid.uuid4().hex[:12]}/leader"


def test_it_never_runs_while_another_member_leads() -> None:
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    put(key, "other")

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=2, holder="a"), name, arena.body("a")) as task:
            for _ in range(12):
                await asyncio.sleep(0.05)
                assert holder_of(name) is None
            assert not task.done()
        assert arena.starts == []

    run(scenario())


def test_it_never_runs_while_the_leader_key_is_absent() -> None:
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    delete(key)

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=2, holder="a"), name, arena.body("a")):
            for _ in range(12):
                await asyncio.sleep(0.05)
                assert holder_of(name) is None
        assert arena.starts == []

    run(scenario())


@pytest.mark.parametrize("value", ["ab", "", " a", "a ", "A"])
def test_only_the_exact_member_name_counts(value: str) -> None:
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    put(key, value)

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=2, holder="a"), name, arena.body("a")):
            await asyncio.sleep(0.8)
            assert holder_of(name) is None
        assert arena.starts == []

    run(scenario())


def test_it_starts_once_its_member_becomes_the_leader() -> None:
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    put(key, "other")

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=2, holder="a"), name, arena.body("a")):
            await asyncio.sleep(0.5)
            assert arena.starts == []
            put(key, "a")
            await wait_until(lambda: arena.starts, timeout=6)
            assert holder_of(name) == "a"
        assert holder_of(name) is None

    run(scenario())


def test_it_starts_when_the_leader_key_appears_after_an_election() -> None:
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    delete(key)

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=2, holder="a"), name, arena.body("a")):
            await asyncio.sleep(0.4)
            put(key, "a")
            await wait_until(lambda: arena.starts, timeout=6)

    run(scenario())


def test_the_leader_moving_away_cancels_the_body_and_frees_the_key_before_the_lease_could_expire() -> None:
    """ttl=5: a holder that merely stopped refreshing would keep the key for five seconds."""
    etcd, name, arena, key = FakeStand(), unique_name(), Arena(), leader_key()
    etcd.put(key, "a")

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        async with campaign(etcd.lease(ActiveSite("a", key), 5, "a"), name, arena.body("a")) as task:
            await wait_until(lambda: arena.starts)
            assert etcd.holder_of(name) == "a"
            moved = loop.time()
            etcd.put(key, "other")
            await wait_until(lambda: arena.cancels and etcd.holder_of(name) is None, timeout=4)
            assert loop.time() - moved < 2.5
            assert arena.running == 0
            assert not task.done(), "run goes back to waiting; it does not end"
            etcd.put(key, "a")
            await wait_until(lambda: arena.starts == ["a", "a"], timeout=6)

    etcd.run(scenario())


def test_the_leader_key_vanishing_also_releases() -> None:
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    put(key, "a")

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=5, holder="a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            delete(key)
            await wait_until(lambda: arena.cancels and holder_of(name) is None, timeout=4)

    run(scenario())


def test_the_release_is_logged_with_its_reason(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    put(key, "a")
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=5, holder="a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            put(key, "other")
            await wait_until(lambda: holder_of(name) is None and arena.cancels, timeout=4)

    run(scenario())
    released = events(capsys.readouterr().out, "lease.released", name)
    assert released
    assert released[0].get("reason") == "not_active_site"


def test_the_standby_site_takes_over_when_leadership_moves() -> None:
    etcd, name, arena, key = FakeStand(), unique_name(), Arena(), leader_key()
    etcd.put(key, "a")

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            for member in ("a", "b"):
                lease = etcd.lease(ActiveSite(member, key), 5, member)
                await stack.enter_async_context(campaign(lease, name, arena.body(member)))
            await wait_until(lambda: arena.starts)
            await asyncio.sleep(0.5)
            assert arena.starts == ["a"]
            etcd.put(key, "b")
            await wait_until(lambda: arena.starts == ["a", "b"], timeout=4)
            assert arena.max_running == 1
            assert etcd.holder_of(name) == "b"

    etcd.run(scenario())


def test_two_sites_never_run_at_once_while_leadership_moves_back_and_forth() -> None:
    etcd, name, arena, key = FakeStand(), unique_name(), Arena(), leader_key()
    etcd.put(key, "a")

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            for member in ("a", "b"):
                lease = etcd.lease(ActiveSite(member, key), 2, member)
                await stack.enter_async_context(campaign(lease, name, arena.body(member)))
            await wait_until(lambda: arena.starts == ["a"])
            for step, member in enumerate(["b", "a", "b", "a"], start=2):
                etcd.put(key, member)
                await wait_until(lambda: len(arena.starts) == step and arena.running == 1, timeout=6)
                assert arena.starts[-1] == member
                assert etcd.holder_of(name) == member
            assert arena.max_running == 1

    etcd.run(scenario())


def test_a_site_that_is_not_active_logs_standby_once_per_wait(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    etcd, name, arena, key = FakeStand(), unique_name(), Arena(), leader_key()
    etcd.put(key, "other")
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(etcd.lease(ActiveSite("a", key), 2, "a"), name, arena.body("a")):
            await asyncio.sleep(1.6)
            assert len(events(capsys.readouterr().out, "lease.standby")) == 1
            etcd.put(key, "a")
            await wait_until(lambda: arena.starts, timeout=6)
            etcd.put(key, "other")
            await wait_until(lambda: arena.cancels and etcd.holder_of(name) is None, timeout=4)
            await asyncio.sleep(1.2)
            assert len(events(capsys.readouterr().out, "lease.standby")) == 1

    etcd.run(scenario())


def test_an_active_site_does_not_log_standby(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    put(key, "a")
    capsys.readouterr()

    async def scenario() -> None:
        async with campaign(EtcdLease(url, ActiveSite("a", key), ttl=2, holder="a"), name, arena.body("a")):
            await wait_until(lambda: arena.starts)
            await asyncio.sleep(0.5)

    run(scenario())
    assert events(capsys.readouterr().out, "lease.standby") == []


class LeaderMovesBeforeClaim(httpx2.AsyncBaseTransport):
    """Forwards everything, but just before the first transaction reaches etcd the leader key moves to `other`: the
    window between a campaign's site check and its claim."""

    def __init__(self, key: str) -> None:
        self.key, self.moved = key, False
        self._inner = httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/kv/txn") and not self.moved:
            self.moved = True
            put(self.key, "other")
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def test_the_site_check_and_the_claim_are_one_transaction() -> None:
    """Directed at a surviving mutant (a claim without the site guard): leadership moving between the check and the
    claim must leave the key unclaimed."""
    url, name, arena, key = etcd_url(), unique_name(), Arena(), leader_key()
    put(key, "a")
    transport = LeaderMovesBeforeClaim(key)

    async def scenario() -> None:
        connect = EtcdGateway.connect(url, transport=transport)
        lease = EtcdLease(url, ActiveSite("a", key), ttl=2, holder="a", connect=connect)
        async with campaign(lease, name, arena.body("a")):
            await wait_until(lambda: transport.moved)
            await asyncio.sleep(0.6)
            assert holder_of(name) is None
        assert arena.starts == []

    run(scenario())
