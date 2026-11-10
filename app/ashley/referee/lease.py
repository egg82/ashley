"""The interface every singleton runs under. A singleton is anything she does on her own initiative; run on both sites
at once, she does it twice."""

import asyncio
from abc import abstractmethod
from collections.abc import Callable, Coroutine
from typing import Any

from ..services import Service

Body = Callable[[], Coroutine[Any, Any, None]]


class Lease(Service):
    """Runs a singleton's body only while this process holds the lease named for it, on the active site."""

    @classmethod
    def null(cls) -> "Lease":
        return NullLease()

    @abstractmethod
    async def run(self, name: str, body: Body) -> None:
        """Run until cancelled, calling `body()` only while this process holds the lease `name`.

        - Across every process using the same etcd, at most one runs a body for a given `name` at any moment.
        - A process campaigns, and takes the lease, only while its site is the active site (`ActiveSite`); the check
          and the claim are one etcd transaction. While it holds the lease it re-checks on every keepalive, and once
          its site is no longer active it cancels the body and releases the lease, so another site can take it.
        - When the lease is lost (etcd says it expired, or no keepalive has succeeded for long enough that it might
          have), the body is cancelled before the lease can expire in etcd, and `run` campaigns again.
        - When the body returns or raises, the lease is released at once, so another process can take it, and `run`
          campaigns again after a pause.
        - When `run` is cancelled, the body is cancelled and the lease released.
        - The body must let `asyncio.CancelledError` through; one that swallows it keeps running without the lease.

        Logs `lease.taken`, `lease.lost` and `lease.released` (each with `name` and `reason` where there is one),
        `lease.held_elsewhere` once each time it starts waiting on another holder, `lease.standby` once each time it
        starts waiting for its site to become active, and `lease.etcd_unreachable` once per run of failed calls. A
        release because the site stopped being active has `reason=not_active_site`."""

    async def run_on_site(self, name: str, body: Body) -> None:
        """Like `run`, but the lease is this site's own: at most one process on this site runs `body` for `name` at any
        moment, whichever site is active, so each site has its holder (for what lives in this site's cluster, like a
        pod). Takes the same care as `run` when the lease is lost or the body ends; logs the same events under
        `name@<site>`, and never `lease.standby` or `not_active_site`. An implementation with no notion of a site
        answers as `run` does."""
        await self.run(name, body)


class NullLease(Lease):
    """Never holds a lease, so never runs a body: an unwired process must not act on its own initiative."""

    async def run(self, name: str, body: Body) -> None:
        await asyncio.Event().wait()
