"""Proton Bridge as a leased singleton (`decisions.md`, "Bridge runs as a leased singleton whose vault outlives its
pod"). `run` is the body wiring starts under `ashley.referee.lease.Lease` named `NAME`, so only the site whose Patroni
member leads keeps a Bridge. Each tick it reads the record's holder and what the pod is doing, and takes the step
`proton_fence.decide` names: adopt a pod of this site that is heard from, raise the epoch to retire any other, make the
next pod once the older epoch's fence has run out. A holder that loses the lease deletes nothing, so the next adopts.

Logs `proton_bridge.started`, `.adopted`, `.retired` and `.stopped` (epoch, site, reason) and `proton_bridge.failed` (the
error's type or status), never a token."""

import asyncio
import logging
import secrets
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from .. import logs
from ..runs.kube_api import KubeApi, KubeError
from ..runs.loose import as_list, as_object
from ..services import Service
from . import proton_pod, proton_tls
from .config import MailConfig
from .proton_bridge import BridgeUnavailable, Holder, KeeperAccess, ProtonBridge
from .proton_bridge_postgres import token_sha256
from .proton_fence import Decision, PodState, Step, decide

log = logging.getLogger("ashley.mail")
NAME = "proton_bridge"


class Keeping(Service):
    """The upkeep of Bridge's pod, reached through the locator so `wiring_singletons` can start it where wiring made one."""

    @classmethod
    def null(cls) -> "Keeping":
        return NullKeeping()

    @abstractmethod
    async def run(self) -> None:
        """Keep Bridge until cancelled."""


class NullKeeping(Keeping):
    """Keeps nothing: Bridge is not wired here."""

    async def run(self) -> None:
        await asyncio.Event().wait()


class BridgeKeeping(Keeping):
    def __init__(self, bridge: ProtonBridge, api: KubeApi, namespace: str, image: str, app_url: str, site: str,
                 config: MailConfig, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        """`image` is the pinned Bridge image, `app_url` where its pod reaches the app, `site` this site's Patroni
        member name."""
        self._bridge = bridge
        self._api = api
        self._namespace = namespace
        self._image = image
        self._app_url = app_url
        self._site = site
        self._config = config
        self._sleep = sleep
        self._seen_epoch = 0

    async def run(self) -> None:
        """Keep Bridge until cancelled; a failed call is logged and tried again at the next tick."""
        while True:
            try:
                await self.tick()
            except (KubeError, BridgeUnavailable) as e:
                logs.warning(log, "proton_bridge.failed", site=self._site, error=str(e))
            await self._sleep(self._config.tick_s)

    async def tick(self) -> Decision:
        """Look once and take the step; the decision it acted on."""
        holder = await self._bridge.holder()
        decision = decide(holder, self._site, await self._pod_state(holder), self._config.fence_s,
                          self._config.fence_margin_s)
        if decision.step is Step.ADOPT:
            await self._adopt(holder)
        elif decision.step is Step.RAISE:
            await self._raise(holder, decision.reason)
        elif decision.step is Step.REPLACE:
            await self._replace(holder)
        elif decision.step is Step.MAKE:
            await self._make(holder)
        return decision

    async def _pod_state(self, holder: Holder) -> PodState:
        if holder.pod is None or holder.site != self._site:
            return "absent"
        pod = await self._api.pod(self._namespace, holder.pod)
        meta = as_object((pod or {}).get("metadata")) or {}
        if pod is None or meta.get("deletionTimestamp"):
            return "absent"
        phase = (as_object(pod.get("status")) or {}).get("phase")
        if phase in ("Failed", "Succeeded"):
            return "ended"
        return "running" if _image_of(pod) == self._image else "stale"

    async def _adopt(self, holder: Holder) -> None:
        if self._seen_epoch != holder.epoch:
            self._seen_epoch = holder.epoch
            logs.info(log, "proton_bridge.adopted", epoch=holder.epoch, site=self._site)
            await self._sweep(holder.epoch)

    async def _raise(self, holder: Holder, reason: str) -> int | None:
        token = secrets.token_urlsafe(32)
        pair = proton_tls.make()
        access = KeeperAccess(token, pair[proton_tls.CERT_KEY])
        epoch = await self._bridge.raise_epoch(holder.epoch, self._site, token_sha256(token), access)
        if epoch is None:
            return None
        logs.info(log, "proton_bridge.retired", epoch=holder.epoch, site=holder.site or "none", reason=reason)
        await self._api.create_secret(self._namespace, proton_pod.pod_name(epoch), proton_pod.secret_labels(epoch),
                                      {proton_pod.TOKEN_KEY: token, **pair})
        await self._sweep(epoch)
        return epoch

    async def _replace(self, holder: Holder) -> None:
        logs.info(log, "proton_bridge.stopped", epoch=holder.epoch, site=self._site, reason="ended")
        await self._sleep(self._config.restart_s)
        epoch = await self._raise(holder, "ended")
        if epoch is not None:
            await self._start(epoch)

    async def _make(self, holder: Holder) -> None:
        name = proton_pod.pod_name(holder.epoch)
        known = await self._api.secret(self._namespace, name)
        if known is None or proton_pod.TOKEN_KEY not in known:
            await self._raise(holder, "token_lost")
            return
        await self._start(holder.epoch)

    async def _start(self, epoch: int) -> None:
        if not await self._bridge.pod_started(epoch, proton_pod.pod_name(epoch)):
            return
        await self._api.create_pod(self._namespace, proton_pod.manifest(epoch, self._image, self._app_url, self._config))
        self._seen_epoch = epoch
        logs.info(log, "proton_bridge.started", epoch=epoch, site=self._site)

    async def _sweep(self, current: int) -> None:
        """Delete this cluster's Bridge pods and token Secrets of every epoch but `current`."""
        keep = proton_pod.pod_name(current)
        selector = f"{proton_pod.LABEL}=true"
        for pod in await self._api.pods(self._namespace, selector):
            name = _name(pod)
            if name is not None and name != keep and await self._api.delete_pod(self._namespace, name):
                logs.info(log, "proton_bridge.stopped", epoch=_epoch_of(name), site=self._site, reason="superseded")
        for name in await self._api.secrets(self._namespace, selector):
            if name != keep:
                await self._api.delete_secret(self._namespace, name)


def _name(pod: dict[str, Any]) -> str | None:
    name = (as_object(pod.get("metadata")) or {}).get("name")
    return name if isinstance(name, str) else None


def _image_of(pod: dict[str, Any]) -> str | None:
    containers = as_list((as_object(pod.get("spec")) or {}).get("containers")) or [None]
    image = (as_object(containers[0]) or {}).get("image")
    return image if isinstance(image, str) else None


def _epoch_of(name: str) -> int:
    tail = name.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


async def run(keeping: BridgeKeeping) -> None:
    """The singleton's body: keep Bridge until cancelled."""
    await keeping.run()
