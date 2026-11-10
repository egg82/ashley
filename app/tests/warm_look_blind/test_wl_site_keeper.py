"""The warm pod's keeper under the lease: each site's app pods keep one pod in their own cluster, one keeper per
site, and a holder that takes over adopts the pod it finds; wiring starts the keeper under `Lease.run_on_site` named
`look-warm` when the looker is the warm one, and under no other lease."""

import asyncio
from contextlib import AsyncExitStack, suppress

from ashley import services
from ashley.looks.looker import Looker
from ashley.looks.warm_looker import WarmLooker
from ashley.looks.warm_pod import NAME, WarmPod
from ashley.referee.active_site import ActiveSite
from ashley.referee.etcd_lease import EtcdLease
from ashley.referee.lease import Body, Lease, NullLease
from ashley.settings import Settings
from ashley.wiring_singletons import singletons
from contract.lease_support import put, run, unique_name, wait_until
from etcd import etcd_url
from warm_blind_support import CONFIG, WARM_URL, FakeCold, FakeKube, go, keeper, mock_client, text_reply, with_config

LEADER = "/ashley-test/warm-look-site-leader"
FAST = with_config(warm_tick_s=0.05)


def pod_of(kube: FakeKube) -> WarmPod:
    return keeper(kube, FAST)


def test_each_site_keeps_one_pod_in_its_own_cluster() -> None:
    put(LEADER, "a")
    name = unique_name()
    clusters = {"a": FakeKube(), "b": FakeKube()}

    async def scenario() -> None:
        async with AsyncExitStack() as stack:
            tasks: list[asyncio.Task[None]] = []
            for tag, site in (("a1", "a"), ("a2", "a"), ("b1", "b"), ("b2", "b")):
                lease = EtcdLease(etcd_url(), ActiveSite(site, LEADER), ttl=2, holder=tag)
                tasks.append(asyncio.create_task(lease.run_on_site(name, pod_of(clusters[site]).run)))
            stack.callback(lambda: [t.cancel() for t in tasks])
            await wait_until(lambda: all(NAME in k.pods_by_name for k in clusters.values()))
            await asyncio.sleep(0.6)
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    run(scenario())
    for kube in clusters.values():
        assert kube.count("create") == 1 and kube.count("delete") == 0


def test_a_holder_that_takes_over_adopts_the_pod_and_makes_no_second() -> None:
    put(LEADER, "a")
    name, kube = unique_name(), FakeKube()

    async def scenario() -> None:
        first = asyncio.create_task(EtcdLease(etcd_url(), ActiveSite("a", LEADER), ttl=2, holder="a1").run_on_site(name, pod_of(kube).run))
        await wait_until(lambda: NAME in kube.pods_by_name)
        kube.pods_by_name[NAME]["status"]["phase"] = "Running"
        second = asyncio.create_task(EtcdLease(etcd_url(), ActiveSite("a", LEADER), ttl=2, holder="a2").run_on_site(name, pod_of(kube).run))
        await asyncio.sleep(0.4)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        before = kube.count("get")
        await wait_until(lambda: kube.count("get") > before + 3, timeout=10)
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)

    run(scenario())
    assert kube.count("create") == 1 and kube.count("delete") == 0


class RecordedLease(Lease):
    def __init__(self) -> None:
        self.on_site: dict[str, Body] = {}
        self.active: list[str] = []

    async def run(self, name: str, body: Body) -> None:
        self.active.append(name)

    async def run_on_site(self, name: str, body: Body) -> None:
        self.on_site[name] = body


def started(lease: Lease) -> None:
    services.register(Lease, lease)
    try:
        settings = Settings(database_url="x", build_version="t", etcd_url="http://127.0.0.1:1", site="willow")
        for coroutine in singletons(settings):
            with suppress(asyncio.TimeoutError):
                asyncio.run(asyncio.wait_for(coroutine, 0.3))
    finally:
        services.unregister(Lease)


def with_looker(looker: Looker) -> None:
    services.register(Looker, looker)


def warm_looker(kube: FakeKube) -> WarmLooker:
    client, _ = mock_client(lambda r: text_reply(""))
    return WarmLooker(FakeCold(), keeper(kube, FAST), client, WARM_URL, CONFIG)


def test_the_warm_looker_s_keeper_runs_under_run_on_site_named_look_warm() -> None:
    kube, lease = FakeKube(), RecordedLease()
    with_looker(warm_looker(kube))
    try:
        started(lease)
    finally:
        services.unregister(Looker)
    assert NAME in lease.on_site and NAME not in lease.active
    body = lease.on_site[NAME]

    async def scenario() -> None:
        task = asyncio.create_task(body())
        await wait_until(lambda: NAME in kube.pods_by_name)
        kube.pods_by_name[NAME]["status"]["phase"] = "Failed"
        await wait_until(lambda: kube.count("create") == 2)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    run(scenario())
    assert kube.count("create") == 2 and kube.count("delete") == 1


def test_without_the_warm_looker_there_is_no_keeper() -> None:
    lease = RecordedLease()
    with_looker(FakeCold())
    try:
        started(lease)
    finally:
        services.unregister(Looker)
    assert NAME not in lease.on_site and NAME not in lease.active


def test_the_null_lease_never_starts_the_keeper() -> None:
    kube = FakeKube()
    with_looker(warm_looker(kube))
    try:
        started(NullLease())
    finally:
        services.unregister(Looker)
    assert kube.calls == []


class OnlyRun(Lease):
    """A Lease with no notion of a site: it implements `run` alone."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, Body]] = []

    async def run(self, name: str, body: Body) -> None:
        self.asked.append((name, body))


def test_a_lease_with_no_notion_of_a_site_answers_run_on_site_as_run_does() -> None:
    lease = OnlyRun()

    async def body() -> None:
        return None

    go(lease.run_on_site("some-name", body))
    assert lease.asked == [("some-name", body)]
