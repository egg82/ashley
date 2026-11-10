"""The Kubernetes looker: each look in a pod of its own in the sandbox namespace (`pod_spec.manifest`), running
`shooter.py`; the picture read from the pod's log (`PodLog`, which sweeps the look pods a stopped app pod left behind, the
warm pod excepted). Logs carry the pod's name, the outcome and durations, never the page's address or what it drew."""

import asyncio
import base64
import binascii
import logging
import time
from collections.abc import Awaitable, Callable
from importlib import resources

from ..runs.kube_api import KubeApi
from ..runs.pod_log import PodFailed, PodLog
from .config import LooksConfig
from . import links
from .looker import Looker, LookUnavailable, Shot, Target
from .pod_spec import LABEL, WARM_LABEL, manifest

log = logging.getLogger("ashley.looks")
SHOOTER = resources.files("ashley.looks").joinpath("shooter.py").read_text()
MARK = "ashley-look "
FAILED = "ashley-look-failed "


class KubernetesLooker(Looker):
    def __init__(self, api: KubeApi, namespace: str, runtime_class: str, image: str, app_url: str, link_key: bytes,
                 config: LooksConfig, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> None:
        """`app_url` is where a pod in the namespace reaches the app, no trailing slash; `link_key` signs the page's
        link (`links`)."""
        self._pods = PodLog(api, namespace, LABEL, config.log_bytes, config.poll_s, log, "looks", sleep, clock,
                            exclude=WARM_LABEL, done="drawn")
        self._runtime_class = runtime_class
        self._image = image
        self._app_url = app_url
        self._config = config
        self._wall = wall
        self._link_key = link_key

    def renders(self) -> bool:
        return True

    async def look(self, name: str, target: Target) -> Shot:
        """Raises LookUnavailable when the API cannot be reached or refuses the pod, the pod never ran, or what it
        printed is not a picture. Logs `looks.pod` with the pod, outcome and duration_ms."""
        pod = manifest(name, self.url(target), self._config, self._image, self._runtime_class, SHOOTER)
        try:
            return await self._pods.run_read(pod, self._config.pod_deadline_s, _shot)
        except PodFailed as e:
            raise LookUnavailable(str(e)) from e

    def url(self, target: Target) -> str:
        """The address of the page for `target`, with a link good for `link_ttl_s`."""
        grant = links.Grant(target.household_id, target.person_id, target.bench_id, target.piece_id,
                            int(self._wall()) + self._config.link_ttl_s)
        side = "" if target.view is None else f"?view={target.view}"
        return f"{self._app_url}{links.PAGE}{links.mint(self._link_key, grant)}{side}"


def picture(log_text: str) -> Shot:
    """The picture in a look pod's log: the base64 after the last `MARK` line. Raises LookUnavailable with the reason
    the pod gave (`FAILED` line), or `no_picture` when the log holds neither."""
    for line in reversed(log_text.splitlines()):
        if line.startswith(MARK):
            try:
                data = base64.b64decode(line[len(MARK):], validate=True)
            except binascii.Error as e:
                raise LookUnavailable("bad_picture") from e
            if not data.startswith(b"\xff\xd8\xff"):
                raise LookUnavailable("bad_picture")
            return Shot(data)
        if line.startswith(FAILED):
            raise LookUnavailable(line[len(FAILED):].strip()[:40] or "failed")
    raise LookUnavailable("no_picture")


def _shot(log_text: str) -> Shot:
    try:
        return picture(log_text)
    except LookUnavailable as e:
        raise PodFailed(str(e)) from e
