"""One short-lived pod whose only output is its log: make it, wait for it to end, read its log, delete it however it
ended. Pods a stopped app pod left behind (carrying `label`) are deleted by the next job once they are past twice the
deadline. Logs carry the pod's name, outcome and durations under the event names `<prefix>.pod`, never the log."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from .. import logs
from .kube_api import KubeApi, KubeError
from .loose import as_object

T = TypeVar("T")
START_GRACE_S = 15
"""How long past the pod's deadline to keep asking whether it finished, for the kubelet to report it."""


class PodFailed(Exception):
    """The pod gave no log: the API could not be reached or refused it, it never ran (`never_ran`), ran past its
    deadline (`timed_out`), vanished (`pod_lost`), or its log could not be read (`log_unreadable`). `args[0]` says which."""


class PodLog:
    def __init__(self, api: KubeApi, namespace: str, label: str, log_bytes: int, poll_s: float,
                 log: logging.Logger, event: str, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic, *, exclude: str | None = None, done: str = "ended") -> None:
        """`label` is the label key the jobs' pods carry, `exclude` a label key whose pods are not this job's (the sweep
        leaves them); `event` names the log lines (`<event>.pod`), `done` the outcome logged when the pod's log was read."""
        self._api = api
        self._namespace = namespace
        self._log_bytes = log_bytes
        self._poll_s = poll_s
        self._log = log
        self._event = event
        self._done = done
        self._selector = f"{label}=true" if exclude is None else f"{label}=true,{exclude}!=true"
        self._sleep = sleep
        self._clock = clock

    async def run(self, manifest: dict[str, Any], deadline_s: int) -> str:
        """Create the pod `manifest` (its metadata name is the pod's), wait up to `deadline_s` and a grace, and return its
        log. Raises PodFailed. Logs `<event>.pod` with the pod, outcome and duration_ms."""
        return await self.run_read(manifest, deadline_s, str)

    async def run_read(self, manifest: dict[str, Any], deadline_s: int, read: Callable[[str], T]) -> T:
        """`run`, with the log turned into the result by `read`, which raises PodFailed for a log that is no answer; the pod
        is deleted and the failure logged as for any other."""
        name = str(manifest["metadata"]["name"])
        started = self._clock()
        await self._sweep(deadline_s)
        try:
            await self._api.create_pod(self._namespace, manifest)
            await self._ended(name, started, deadline_s)
            result = read(await self._read(name))
        except (KubeError, PodFailed) as e:
            reason = e.args[0] if e.args else type(e).__name__
            logs.warning(self._log, f"{self._event}.pod", pod=name, outcome="failed", reason=reason,
                         duration_ms=self._ms(started))
            raise PodFailed(str(reason)) from e
        finally:
            await self._delete(name)
        logs.info(self._log, f"{self._event}.pod", pod=name, outcome=self._done, duration_ms=self._ms(started))
        return result

    async def _ended(self, name: str, started: float, deadline_s: int) -> None:
        phase: object = None
        while True:
            try:
                pod = await self._api.pod(self._namespace, name)
            except KubeError as e:
                logs.info(self._log, f"{self._event}.poll_failed", pod=name, error=str(e))
            else:
                if pod is None:
                    raise PodFailed("pod_lost")
                phase = _phase(pod)
                if phase in ("Succeeded", "Failed"):
                    return
            if self._clock() - started > deadline_s + START_GRACE_S:
                raise PodFailed("never_ran" if phase == "Pending" else "timed_out")
            await self._sleep(self._poll_s)

    async def _read(self, name: str) -> str:
        try:
            return await self._api.log(self._namespace, name, self._log_bytes)
        except KubeError as e:
            raise PodFailed("log_unreadable") from e

    async def _delete(self, name: str) -> None:
        try:
            await self._api.delete_pod(self._namespace, name)
        except KubeError as e:
            logs.warning(self._log, f"{self._event}.pod_left", pod=name, error=str(e))

    async def _sweep(self, deadline_s: int) -> None:
        try:
            pods = await self._api.pods(self._namespace, self._selector)
        except KubeError as e:
            logs.warning(self._log, f"{self._event}.sweep_failed", error=str(e))
            return
        now = datetime.now(UTC)
        old = [p for p in pods if _age_s(p, now) > 2 * deadline_s]
        for pod in old:
            await self._delete(str((as_object(pod.get("metadata")) or {}).get("name")))
        if old:
            logs.info(self._log, f"{self._event}.swept", pods=len(old))

    def _ms(self, started: float) -> int:
        return int((self._clock() - started) * 1000)


def _phase(pod: dict[str, Any]) -> object:
    status = as_object(pod.get("status"))
    return None if status is None else status.get("phase")


def _age_s(pod: dict[str, Any], now: datetime) -> float:
    meta = as_object(pod.get("metadata")) or {}
    created = meta.get("creationTimestamp")
    if not isinstance(created, str):
        return 0.0
    try:
        return (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return 0.0
