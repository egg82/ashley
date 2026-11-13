"""Helpers for the lease contract tests: raw etcd access to observe and perturb state, the same calls on the fake
etcd (`FakeStand`), a probe that counts concurrent bodies, and logfmt parsing."""

import asyncio
import base64
import re
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx2
from ashley.referee.active_site import ActiveSite
import virtual_time
from ashley.referee.etcd_lease import PREFIX, EtcdLease
from ashley.referee.lease import Body
from etcd import etcd_url
from etcd_fake import FakeEtcd, Link

FIELD = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')


def unique_name() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    with httpx2.Client(base_url=etcd_url(), timeout=5) as client:
        response = client.post(path, json=body)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data


def _kv(name: str) -> dict[str, Any] | None:
    kvs: list[dict[str, Any]] = _post("/v3/kv/range", {"key": _b64(PREFIX + name)}).get("kvs", [])
    return kvs[0] if kvs else None


def kv_at(key: str) -> dict[str, Any] | None:
    """The raw etcd record at exactly `key`, None when absent."""
    kvs: list[dict[str, Any]] = _post("/v3/kv/range", {"key": _b64(key)}).get("kvs", [])
    return kvs[0] if kvs else None


LEADER = "/ashley-test/leader"


def here() -> ActiveSite:
    """A site that is always active: a leader key no test changes, holding this site's member name."""
    put(LEADER, "here")
    return ActiveSite("here", LEADER)


def put(key: str, value: str) -> None:
    _post("/v3/kv/put", {"key": _b64(key), "value": _b64(value)})


def delete(key: str) -> None:
    _post("/v3/kv/deleterange", {"key": _b64(key)})


def holder_of(name: str) -> str | None:
    """The value of the lease key, or None when nobody holds it."""
    kv = _kv(name)
    return None if kv is None else base64.b64decode(kv.get("value", "")).decode()


def lease_id_of(name: str) -> str | None:
    kv = _kv(name)
    return None if kv is None else str(kv["lease"])


def revoke(lease_id: str) -> None:
    """Expire a holder's lease from outside, as etcd would on its own."""
    _post("/v3/lease/revoke", {"ID": lease_id})


class Arena:
    """Every body in a scenario reports here, so overlap across holders is counted at the moment it happens."""

    def __init__(self) -> None:
        self.running = 0
        self.max_running = 0
        self.starts: list[str] = []
        self.cancels: list[tuple[str, float]] = []
        self.on_cancel: Callable[[], None] | None = None

    def body(self, tag: str, first: str = "block") -> Body:
        """A body for holder `tag`. Its first run `block`s until cancelled, `return`s or `raise`s ValueError; every
        later run blocks."""
        calls = 0

        async def run() -> None:
            nonlocal calls
            calls += 1
            self.running += 1
            self.max_running = max(self.max_running, self.running)
            self.starts.append(tag)
            try:
                if calls == 1 and first == "return":
                    return
                if calls == 1 and first == "raise":
                    raise ValueError("zqSECRETMESSAGE")
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if self.on_cancel is not None:
                    self.on_cancel()
                self.cancels.append((tag, asyncio.get_running_loop().time()))
                raise
            finally:
                self.running -= 1

        return run


@asynccontextmanager
async def campaign(lease: Any, name: str, body: Body) -> AsyncGenerator[asyncio.Task[None]]:
    """`lease.run(name, body)` as a task for the length of the block; cancelled and awaited on the way out. A run that
    ended on its own with an exception raises here."""
    task = asyncio.create_task(lease.run(name, body))
    try:
        yield task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def wait_until(predicate: Callable[[], object], timeout: float = 8.0) -> None:
    """Poll until `predicate` holds, failing after `timeout` seconds of the loop's clock."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "timed out waiting"
        await asyncio.sleep(0.02)


def run(scenario: Awaitable[None], limit: float = 25.0) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, limit)

    asyncio.run(bounded())


class FakeStand:
    """The fake etcd through the calls the real one is reached by above, its scenarios run on the virtual clock."""

    run = staticmethod(virtual_time.run)

    def __init__(self) -> None:
        self.etcd = FakeEtcd()

    def lease(self, site: ActiveSite, ttl: int, holder: str, link: Link | None = None) -> EtcdLease:
        return EtcdLease("", site, ttl=ttl, holder=holder, connect=self.etcd.connect(link))

    def here(self) -> ActiveSite:
        self.etcd.put(LEADER, "here")
        return ActiveSite("here", LEADER)

    def put(self, key: str, value: str) -> None:
        self.etcd.put(key, value)

    def holder_of(self, name: str) -> str | None:
        return self.etcd.value(PREFIX + name)

    def lease_id_of(self, name: str) -> str | None:
        lease_id = self.etcd.lease_of(PREFIX + name)
        return None if lease_id is None else str(lease_id)

    def revoke(self, lease_id: str) -> None:
        self.etcd.revoke(int(lease_id))


class RealStand:
    """The real etcd through the same calls as `FakeStand`, for a test run against both."""

    run = staticmethod(run)

    def __init__(self) -> None:
        self.url = etcd_url()

    def lease(self, site: ActiveSite, ttl: int, holder: str) -> EtcdLease:
        return EtcdLease(self.url, site, ttl=ttl, holder=holder)

    here = staticmethod(here)
    put = staticmethod(put)
    holder_of = staticmethod(holder_of)
    lease_id_of = staticmethod(lease_id_of)
    revoke = staticmethod(revoke)


def events(out: str, event: str, name: str | None = None) -> list[dict[str, str]]:
    """The logfmt lines of `event`, optionally only those carrying `name`."""
    lines = [dict(FIELD.findall(line)) for line in out.splitlines()]
    return [ln for ln in lines if ln.get("event") == event and (name is None or ln.get("name") == name)]
