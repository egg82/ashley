"""The warm look pod's upkeep: one pod per cluster, always named `NAME`, kept so a look does not wait for a pod to start.
`WarmPod.run` is the body of a singleton under the site's own lease (`Lease.run_on_site`), so one app pod per site
keeps it; any app pod reaches the pod through its Service. Each tick it creates the pod when there is none, replaces
one that ended, was made for another image or limits (its `SPEC_ANNOTATION` differs) or has lived past `warm_max_age_s`,
and otherwise leaves it: a holder taking over adopts what is running. Logs `looks.warm_started`, `looks.warm_adopted`,
`looks.warm_replaced` (with the reason) and `looks.warm_failed`, with the pod's age and durations, never a page."""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .. import logs
from ..runs.kube_api import KubeApi, KubeError
from ..runs.labels import PREFIX
from ..runs.loose import as_object
from .config import LooksConfig
from .pod_spec import warm_manifest

log = logging.getLogger("ashley.looks")
NAME = "look-warm"
SPEC_ANNOTATION = PREFIX + "look-spec"
RECHECK_S = 1.0
"""How soon to look again after deleting the pod, to make its replacement."""


class WarmPod:
    def __init__(self, api: KubeApi, namespace: str, runtime_class: str, image: str, prefix: str, shooter: str,
                 config: LooksConfig, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        """`prefix` is the app's look page path the pod may open (`<app url>/look/`), `shooter` the program it runs."""
        self._api = api
        self._namespace = namespace
        self._config = config
        self._sleep = sleep
        self._clock = clock
        manifest = warm_manifest(NAME, prefix, config, image, runtime_class, shooter)
        digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
        manifest["metadata"]["annotations"] = {SPEC_ANNOTATION: digest}
        self._manifest = manifest
        self._digest = digest
        self._seen = False

    async def run(self) -> None:
        """Keep the pod until cancelled; a failed call is logged and tried again at the next tick."""
        while True:
            try:
                changed = await self.tick()
            except KubeError as e:
                changed = False
                logs.warning(log, "looks.warm_failed", pod=NAME, error=str(e))
            await self._sleep(RECHECK_S if changed else self._config.warm_tick_s)

    async def tick(self) -> bool:
        """Look at the pod once and make it right; whether it deleted a pod (to look again soon)."""
        started = self._clock()
        pod = await self._api.pod(self._namespace, NAME)
        if pod is None:
            await self._api.create_pod(self._namespace, self._manifest)
            logs.info(log, "looks.warm_started", pod=NAME, duration_ms=int((self._clock() - started) * 1000))
            self._seen = True
            return False
        reason = self._stale(pod, datetime.now(UTC))
        if reason is not None:
            await self._api.delete_pod(self._namespace, NAME)
            logs.info(log, "looks.warm_replaced", pod=NAME, reason=reason)
            self._seen = False
            return True
        if not self._seen:
            logs.info(log, "looks.warm_adopted", pod=NAME, age_s=int(_age_s(pod, datetime.now(UTC))))
            self._seen = True
        return False

    def _stale(self, pod: dict[str, Any], now: datetime) -> str | None:
        """Why the pod should go, or None. A pod already being deleted is left to finish."""
        meta = as_object(pod.get("metadata")) or {}
        if meta.get("deletionTimestamp"):
            return None
        status = as_object(pod.get("status")) or {}
        if status.get("phase") in ("Failed", "Succeeded"):
            return "ended"
        if (as_object(meta.get("annotations")) or {}).get(SPEC_ANNOTATION) != self._digest:
            return "spec_changed"
        if _age_s(pod, now) > self._config.warm_max_age_s:
            return "aged"
        return None


def _age_s(pod: dict[str, Any], now: datetime) -> float:
    created = (as_object(pod.get("metadata")) or {}).get("creationTimestamp")
    if not isinstance(created, str):
        return 0.0
    try:
        return (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return 0.0
