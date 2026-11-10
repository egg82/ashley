"""The warm Looker: an Object Pool of size one in front of `KubernetesLooker`. A look is sent to the warm pod
(`warm_pod.WarmPod` keeps it) at `warm_url`, which takes one at a time; when that pod is busy, missing, unreachable or
broken, the look is taken the way it always was, in a pod of its own. A page that never drew or a picture too large is
the look's answer, not a reason to try again. Logs `looks.warm` with the outcome, bytes and duration_ms, and
`looks.warm_fallback` with why the look went to a pod of its own."""

import logging
import time
from collections.abc import Callable

import httpx2

from .. import logs
from .config import LooksConfig
from .kubernetes import KubernetesLooker, picture
from .looker import Looker, LookUnavailable, Shot, Target
from .warm_pod import WarmPod

log = logging.getLogger("ashley.looks")
ANSWERS = ("not_ready", "too_large")
"""The reasons a warm pod gives that are about the page, so a pod of its own would only say them again."""


class _Cold(Exception):
    """The warm pod could not take this look."""


class WarmLooker(Looker):
    def __init__(self, cold: KubernetesLooker, keeper: WarmPod, http: httpx2.AsyncClient, warm_url: str,
                 config: LooksConfig, clock: Callable[[], float] = time.monotonic) -> None:
        """`warm_url` is the warm pod's Service, no trailing slash."""
        self.keeper = keeper
        self._cold = cold
        self._http = http
        self._warm_url = warm_url
        self._config = config
        self._clock = clock

    def renders(self) -> bool:
        return True

    async def look(self, name: str, target: Target) -> Shot:
        """As `Looker.look`; `name` names the pod of its own, if the look needs one."""
        started = self._clock()
        try:
            shot = await self._warm(self._cold.url(target))
        except _Cold as e:
            logs.info(log, "looks.warm_fallback", reason=str(e), duration_ms=self._ms(started))
            return await self._cold.look(name, target)
        except LookUnavailable as e:
            logs.warning(log, "looks.warm", outcome="failed", reason=str(e), duration_ms=self._ms(started))
            raise
        logs.info(log, "looks.warm", outcome="drawn", bytes=len(shot.data), duration_ms=self._ms(started))
        return shot

    async def _warm(self, url: str) -> Shot:
        timeout = httpx2.Timeout(self._config.pod_deadline_s, connect=self._config.warm_connect_s)
        try:
            got = await self._http.post(f"{self._warm_url}/look", json={"url": url}, timeout=timeout)
        except httpx2.HTTPError as e:
            raise _Cold(type(e).__name__) from e
        if got.status_code == 503:
            raise _Cold("busy")
        if got.status_code != 200:
            raise _Cold(f"http_{got.status_code}")
        try:
            return picture(got.text)
        except LookUnavailable as e:
            if str(e) in ANSWERS:
                raise
            raise _Cold(str(e)) from e

    def _ms(self, started: float) -> int:
        return int((self._clock() - started) * 1000)
