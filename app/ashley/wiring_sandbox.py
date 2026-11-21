"""Wiring of what runs in pods of the sandbox namespace, through the app's ServiceAccount: code runs, looks at a bench and
media jobs. Called by `ashley.wiring.wire` when `sandbox_token_file` is set."""

import hashlib
import hmac
import logging
import ssl
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

import httpx2

from . import logs, services
from .connections.deployment_secrets import DeploymentSecrets
from .looks import config as looks_config
from .looks import links
from .looks.browser import PageBrowser
from .looks.kubernetes import SHOOTER, KubernetesLooker
from .looks.kubernetes_browser import KubernetesBrowser
from .looks.kubernetes_session import KubernetesSessions
from .looks.looker import Looker
from .looks.session import BrowserSessions
from .looks.warm_looker import WarmLooker
from .looks.warm_pod import WarmPod
from .runs import config as runs_config
from .runs import media_config
from .runs.config import PINNED
from .runs.kube_api import KubeApi
from .runs.kubernetes import KubernetesSandbox
from .runs.media import Media
from .runs.media_kubernetes import KubernetesMedia
from .runs.media_pod import LABEL as MEDIA_LABEL
from .runs.pod_log import PodLog
from .runs.podman import PodmanSandbox
from .runs.sandbox import Sandbox
from .settings import Settings


def _link_key() -> bytes:
    """The deployment's link key in force (`DeploymentSecrets`)."""
    return services.get(DeploymentSecrets).link_key().encode()


def _session_token(pod: str) -> str:
    """The bearer token of the browser session pod named `pod`: its name signed with the deployment's link key, so any app
    pod derives the same one and none is stored."""
    return hmac.new(_link_key(), b"look-session:" + pod.encode(), hashlib.sha256).hexdigest()


def wire_sandbox(settings: Settings, closers: list[Callable[[], Coroutine[Any, Any, None]]],
                 whisper: Callable[[], Awaitable[str]]) -> KubeApi:
    """Register the sandbox, and the Looker (and its warm pod's keeper) and Media when their images are set; `closers` takes what must be closed.
    Returns the Kubernetes API client, for the other pods she keeps. Raises ValueError for an image not pinned by digest (`CAD_IMAGE` and `PYTHON_IMAGE` too). `whisper` gives the speech service's address (`wire_media`)."""
    kube = httpx2.AsyncClient(base_url=settings.sandbox_api_url,
                              verify=ssl.create_default_context(cafile=settings.sandbox_ca_file), timeout=10.0)
    closers.append(kube.aclose)
    sandbox = runs_config.load()
    if settings.cad_image:
        sandbox = sandbox.with_image("build123d", settings.cad_image)
    if settings.python_image:
        sandbox = sandbox.with_image("python", settings.python_image)
    api = KubeApi(kube, settings.sandbox_token_file)
    services.register(Sandbox, KubernetesSandbox(api, sandbox, settings.sandbox_namespace, settings.sandbox_runtime_class))
    if settings.look_image:
        wire_looker(settings, api, closers)
    if settings.media_image:
        wire_media(settings, api, whisper)
    return api


def wire_podman_sandbox() -> None:
    """Register `PodmanSandbox` as the sandbox, for `SANDBOX_PODMAN=trusted`; logs a warning each start, since code she runs
    gets this machine's kernel. No looker or media: those are pods."""
    logs.warning(logging.getLogger("ashley.runs"), "runs.sandbox_podman", isolation="none", kernel="host")
    services.register(Sandbox, PodmanSandbox(runs_config.load()))


def wire_looker(settings: Settings, api: KubeApi,
                closers: list[Callable[[], Coroutine[Any, Any, None]]]) -> None:
    """The Looker: a pod per look, fronted by the warm pod when `look_warm_url` is set; the page browser, a cold pod
    of the same image per page read; and browser sessions, a pod of it per session she drives."""
    if not PINNED.fullmatch(settings.look_image):
        raise ValueError("LOOK_IMAGE must be pinned by a full digest (name@sha256:<64 lowercase hex>)")
    config = looks_config.load()
    services.register(PageBrowser, KubernetesBrowser(api, settings.sandbox_namespace, settings.sandbox_runtime_class, settings.look_image, config))
    http = httpx2.AsyncClient()
    closers.append(http.aclose)
    services.register(BrowserSessions, KubernetesSessions(api, http, settings.sandbox_namespace, settings.sandbox_runtime_class,
                                                           settings.look_image, config, _session_token))
    cold = KubernetesLooker(api, settings.sandbox_namespace, settings.sandbox_runtime_class, settings.look_image, settings.look_app_url,
                            _link_key, config)
    if not settings.look_warm_url:
        services.register(Looker, cold)
        return
    prefix = settings.look_app_url + links.PAGE
    keeper = WarmPod(api, settings.sandbox_namespace, settings.sandbox_runtime_class, settings.look_image, prefix, SHOOTER, config)
    services.register(Looker, WarmLooker(cold, keeper, http, settings.look_warm_url, config))


def wire_media(settings: Settings, api: KubeApi, whisper: Callable[[], Awaitable[str]]) -> None:
    """Media jobs in pods beside code runs; the pod reaches the speech service at the address `whisper` gives (the Wyoming connection's), if there is one."""
    if not PINNED.fullmatch(settings.media_image):
        raise ValueError("MEDIA_IMAGE must be pinned by a full digest (name@sha256:<64 lowercase hex>)")
    config = media_config.load()
    pods = PodLog(api, settings.sandbox_namespace, MEDIA_LABEL, config.log_bytes, config.poll_s, logging.getLogger("ashley.runs"), "media")
    services.register(Media, KubernetesMedia(pods, settings.sandbox_runtime_class, settings.media_image, settings.media_app_url,
                                             _link_key, whisper, config))
