"""`Lease` on the 3-site etcd. Each singleton name is one key, `/ashley/singletons/<name>`, created under a lease only
when no such key exists and this site is the active one (`ActiveSite`); holding the key is holding the singleton."""

import asyncio
import logging
import socket
import time

import httpx2

from .. import logs
from .active_site import ActiveSite
from .etcd_gateway import EtcdGateway, EtcdTls, EtcdUnavailable
from .lease import Body, Lease
from .lease_log import Streak, log_outcome, outcome

log = logging.getLogger("ashley.referee")

PREFIX = "/ashley/singletons/"


class EtcdLease(Lease):
    """`ttl` is the lease's time to live in seconds. A keepalive goes out every `ttl / 5`; the body is cancelled once
    `ttl / 3` remains on the last confirmed refresh, which leaves that long for it to stop before etcd frees the key.
    `site` says when this process's site is active; each keepalive also reads it, so a holder lets go within about
    `ttl / 5` of its site losing the database. `gated` False is the lease of `run_on_site`, which no site's
    activity bears on."""

    def __init__(self, url: str, site: ActiveSite, tls: EtcdTls | None = None, ttl: int = 15,
                 holder: str | None = None, transport: httpx2.AsyncBaseTransport | None = None,
                 gated: bool = True) -> None:
        self._url = url
        self._site = site
        self._gated = gated
        self._tls = tls
        self._ttl = ttl
        self._interval = ttl / 5
        self._margin = ttl / 3
        self._holder = holder or socket.gethostname()
        self._transport = transport

    async def run_on_site(self, name: str, body: Body) -> None:
        sibling = EtcdLease(self._url, self._site, self._tls, self._ttl, self._holder, self._transport, gated=False)
        await sibling.run(f"{name}@{self._site.member}", body)

    async def run(self, name: str, body: Body) -> None:
        streak = Streak()
        async with EtcdGateway(self._url, self._interval, self._tls, self._transport) as etcd:
            while True:
                lease_id, deadline = await self._campaign(etcd, name, streak)
                streak.reset()
                await self._hold(etcd, name, lease_id, deadline, body)
                await asyncio.sleep(self._interval)

    async def _campaign(self, etcd: EtcdGateway, name: str, streak: Streak) -> tuple[int, float]:
        """Wait until this process holds the key; its lease id and the moment the body must stop by."""
        while True:
            try:
                if self._gated and await etcd.get(self._site.key) != self._site.member:
                    streak.once("lease.standby", name=name, member=self._site.member)
                    await asyncio.sleep(self._interval)
                    continue
                sent = time.monotonic()
                grant = await etcd.grant(self._ttl)
                if await self._claim(etcd, name, grant.lease_id):
                    return grant.lease_id, sent + grant.ttl - self._margin
                await etcd.revoke(grant.lease_id)
                streak.once("lease.held_elsewhere", name=name)
            except EtcdUnavailable as e:
                streak.once("lease.etcd_unreachable", name=name, error=str(e), status=e.status)
            await asyncio.sleep(self._interval)

    async def _claim(self, etcd: EtcdGateway, name: str, lease_id: int) -> bool:
        """Cancelled mid-call, etcd may already have put the key; revoking the lease removes it either way."""
        try:
            guard = (self._site.key, self._site.member) if self._gated else None
            return await etcd.claim(PREFIX + name, self._holder, lease_id, guard)
        except asyncio.CancelledError:
            try:
                await etcd.revoke(lease_id)
            except EtcdUnavailable:
                pass  # the key then expires with the lease
            raise

    async def _hold(self, etcd: EtcdGateway, name: str, lease_id: int, deadline: float, body: Body) -> None:
        logs.info(log, "lease.taken", name=name, lease=f"{lease_id:x}")
        task = asyncio.create_task(body())
        try:
            reason = await self._keep(etcd, lease_id, deadline, task)
        except asyncio.CancelledError:
            await self._stop(task, name)
            await self._release(etcd, name, lease_id, "stopped")
            raise
        if task.done():
            log_outcome(task, name, lease=f"{lease_id:x}")
            await self._release(etcd, name, lease_id, reason)
        elif reason == "not_active_site":
            await self._stop(task, name)
            await self._release(etcd, name, lease_id, reason)
        else:
            await self._stop(task, name)
            logs.warning(log, "lease.lost", name=name, lease=f"{lease_id:x}", reason=reason)

    async def _keep(self, etcd: EtcdGateway, lease_id: int, deadline: float, task: asyncio.Task[None]) -> str:
        """Refresh the lease until the body finishes or the lease is lost; which of those happened."""
        while True:
            next_at = min(time.monotonic() + self._interval, deadline)
            await asyncio.wait({task}, timeout=max(0.0, next_at - time.monotonic()))
            if task.done():
                return outcome(task)
            if time.monotonic() >= deadline:
                return "deadline"
            sent = time.monotonic()
            try:
                ttl = await asyncio.wait_for(etcd.keepalive(lease_id), max(0.0, deadline - sent))
            except (EtcdUnavailable, TimeoutError):
                continue
            if ttl <= 0:
                return "expired"
            deadline = sent + ttl - self._margin
            if self._gated and not await self._still_active(etcd, deadline):
                return "not_active_site"

    async def _still_active(self, etcd: EtcdGateway, deadline: float) -> bool:
        """False only when etcd answered and the site is not active; an unanswered read is the keepalive's business."""
        try:
            leader = await asyncio.wait_for(etcd.get(self._site.key), max(0.0, deadline - time.monotonic()))
        except (EtcdUnavailable, TimeoutError):
            return True
        return leader == self._site.member

    async def _stop(self, task: asyncio.Task[None], name: str) -> None:
        task.cancel()
        await asyncio.wait({task}, timeout=self._margin)
        if not task.done():
            logs.error(log, "lease.body_overran", name=name)

    async def _release(self, etcd: EtcdGateway, name: str, lease_id: int, reason: str) -> None:
        logs.info(log, "lease.released", name=name, lease=f"{lease_id:x}", reason=reason)
        try:
            await etcd.revoke(lease_id)
        except EtcdUnavailable as e:
            logs.warning(log, "lease.revoke_failed", name=name, lease=f"{lease_id:x}", status=e.status)

