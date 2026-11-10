"""The Kubernetes page browser: each read in a cold pod of its own (`pod_spec.read_manifest`), running `shooter.py` in its
`read` mode; what the browser was given read from the pod's log (`PodLog`, the looks' own sweep and label). Never the
warm pod, which has no public egress. Logs carry the pod's name, outcome and durations, never the page's address."""

import asyncio
import base64
import binascii
import logging
import secrets
import time
from collections.abc import Awaitable, Callable

from ..runs.kube_api import KubeApi
from ..runs.pod_log import PodFailed, PodLog
from .browser import Browsed, BrowseUnavailable, PageBrowser
from .config import LooksConfig
from .kubernetes import FAILED, SHOOTER
from .pod_spec import LABEL, WARM_LABEL, read_manifest

log = logging.getLogger("ashley.looks")
READ = "ashley-read "


class KubernetesBrowser(PageBrowser):
    def __init__(self, api: KubeApi, namespace: str, runtime_class: str, image: str, config: LooksConfig,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._pods = PodLog(api, namespace, LABEL, config.log_bytes, config.poll_s, log, "looks.read", sleep, clock,
                            exclude=WARM_LABEL, done="read")
        self._runtime_class = runtime_class
        self._image = image
        self._config = config

    def reads(self) -> bool:
        return True

    async def read(self, url: str) -> Browsed:
        """Raises BrowseUnavailable when the API cannot be reached or refuses the pod, the pod never ran, or what it
        printed is not a page. Logs `looks.read.pod` with the pod, outcome and duration_ms."""
        name = f"read-{secrets.token_hex(6)}"
        pod = read_manifest(name, url, self._config, self._image, self._runtime_class, SHOOTER)
        try:
            return await self._pods.run_read(pod, self._config.pod_deadline_s, _browsed)
        except PodFailed as e:
            raise BrowseUnavailable(str(e)) from e


def browsed(log_text: str) -> Browsed:
    """What a read pod's log says the browser was given: the last `READ` line's status, content type, whether it was
    cut, and the document in base64. Raises BrowseUnavailable with the reason the pod gave (`FAILED`), or `no_page` when
    the log holds neither."""
    for line in reversed(log_text.splitlines()):
        if line.startswith(READ):
            fields = line[len(READ):].split(" ")
            if len(fields) != 4 or not fields[0].isdigit() or fields[2] not in ("cut", "whole"):
                raise BrowseUnavailable("bad_page")
            try:
                data = base64.b64decode(fields[3], validate=True)
            except binascii.Error as e:
                raise BrowseUnavailable("bad_page") from e
            kind = "" if fields[1] == "-" else fields[1]
            return Browsed(int(fields[0]), kind, data.decode("utf-8", errors="ignore"), len(data), fields[2] == "cut")
        if line.startswith(FAILED):
            raise BrowseUnavailable(line[len(FAILED):].strip()[:40] or "failed")
    raise BrowseUnavailable("no_page")


def _browsed(log_text: str) -> Browsed:
    try:
        return browsed(log_text)
    except BrowseUnavailable as e:
        raise PodFailed(str(e)) from e
