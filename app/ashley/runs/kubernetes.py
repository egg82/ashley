"""The Kubernetes sandbox: each job in a pod of its own in the sandbox namespace, under gVisor, with no network, no
token and a deadline (`pod_spec.manifest`); its output read from the pod's log; the pod deleted however the run
ends. Pods a stopped app pod left behind are deleted by the next run once they are past twice the longest pod deadline.
Logs carry the pod's name, the outcome and durations, never the script or what it printed."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from .. import logs
from . import envelope
from .config import Profile, RunsConfig
from .kube_api import KubeApi, KubeError
from .loose import as_list, as_object
from .model import Job, Language, Output
from .pod_spec import LABEL, manifest
from .sandbox import Sandbox, SandboxUnavailable

log = logging.getLogger("ashley.runs")
RUNNER = resources.files("ashley.runs").joinpath("runner.py").read_text()
UNKNOWN = Output("unknown", None, "", "")
START_GRACE_S = 15
"""How long past the pod's deadline to keep asking whether it finished, for the kubelet to report it."""


class KubernetesSandbox(Sandbox):
    def __init__(self, api: KubeApi, config: RunsConfig,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._api = api
        self._config = config
        self._sleep = sleep
        self._clock = clock

    def languages(self) -> tuple[Language, ...]:
        return self._config.offered()

    async def run(self, job: Job) -> Output:
        """Raises SandboxUnavailable when the API cannot be reached or refuses the pod, or the pod is seen pending
        past its deadline: nothing ran. Once the pod exists, a failed read of it is asked again until past its
        deadline, and what cannot be learned then is the outcome `unknown`, since the script may have run. Logs
        `runs.sandbox` with the pod, outcome and duration_ms. A language it was given no image for is unavailable,
        before any pod."""
        started = self._clock()
        profile = self._config.profile(job.language)
        if profile is None:
            logs.warning(log, "runs.sandbox", pod=job.name, outcome="unavailable", language=job.language,
                         error="language not run")
            raise SandboxUnavailable(f"{job.language} is not run")
        await self._sweep()
        try:
            await self._api.create_pod(self._config.namespace, manifest(job, self._config, RUNNER))
            output = await self._finished(job.name, started, profile)
        except KubeError as e:
            logs.warning(log, "runs.sandbox", pod=job.name, outcome="unavailable", error=str(e),
                         duration_ms=self._ms(started))
            raise SandboxUnavailable(str(e)) from e
        finally:
            await self._delete(job.name)
        logs.info(log, "runs.sandbox", pod=job.name, outcome=output.outcome, exit_code=output.exit_code,
                  duration_ms=self._ms(started))
        return output

    async def _finished(self, name: str, started: float, profile: Profile) -> Output:
        """Raises KubeError only for a pod last seen pending past its deadline."""
        phase: object = None
        while True:
            try:
                pod = await self._api.pod(self._config.namespace, name)
            except KubeError as e:
                logs.info(log, "runs.poll_failed", pod=name, error=str(e))
            else:
                if pod is None:
                    return UNKNOWN
                phase = _get(pod, "status", "phase")
                if phase in ("Succeeded", "Failed"):
                    return await self._read(name, pod, profile)
            if self._clock() - started > profile.pod_deadline_s + START_GRACE_S:
                if phase == "Pending":
                    raise KubeError("pod never ran")
                return Output("timed_out", None, "", "") if phase == "Running" else UNKNOWN
            await self._sleep(self._config.poll_s)

    async def _read(self, name: str, pod: dict[str, Any], profile: Profile) -> Output:
        try:
            text: str | None = await self._api.log(self._config.namespace, name, profile.log_bytes)
        except KubeError as e:
            logs.info(log, "runs.log_failed", pod=name, error=str(e))
            text = None
        found = None if text is None else envelope.parse(text, self._config, profile.artifact_bytes)
        if found is not None:
            return found
        if _get(pod, "status", "reason") == "DeadlineExceeded":
            return Output("timed_out", None, "", "")
        statuses = as_list(_get(pod, "status", "containerStatuses")) or [{}]
        first: object = statuses[0]
        if _get(first, "state", "terminated", "reason") == "OOMKilled":
            return Output("out_of_memory", None, "", "")
        return UNKNOWN if text is None else Output("failed", None, "", "")

    async def _delete(self, name: str) -> None:
        try:
            await self._api.delete_pod(self._config.namespace, name)
        except KubeError as e:
            logs.warning(log, "runs.pod_left", pod=name, error=str(e))

    async def _sweep(self) -> None:
        """Delete this app's run pods older than twice the longest pod deadline of any language; a failure is logged and the run goes on."""
        try:
            pods = await self._api.pods(self._config.namespace, f"{LABEL}=true")
        except KubeError as e:
            logs.warning(log, "runs.sweep_failed", error=str(e))
            return
        now = datetime.now(UTC)
        old = [p for p in pods if _age_s(p, now) > 2 * self._config.longest_deadline_s()]
        for pod in old:
            await self._delete(str(_get(pod, "metadata", "name")))
        if old:
            logs.info(log, "runs.swept", pods=len(old))

    def _ms(self, started: float) -> int:
        return int((self._clock() - started) * 1000)


def _get(data: object, *path: str) -> object:
    """The value at `path` in nested JSON objects, None when any step is missing or not an object."""
    for key in path:
        found = as_object(data)
        if found is None:
            return None
        data = found.get(key)
    return data


def _age_s(pod: dict[str, Any], now: datetime) -> float:
    created = _get(pod, "metadata", "creationTimestamp")
    if not isinstance(created, str):
        return 0.0
    try:
        return (now - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return 0.0
