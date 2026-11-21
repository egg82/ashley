"""The Kubernetes browser sessions: each session in a pod of its own (`pod_spec.session_manifest`) running `driver.py`,
reached over HTTP at the pod's address with a token derived from the pod's name (`token`), so any app pod of either site
can drive a session another started: the pod is found by the labels it carries, and holds the session's clock and action
count itself. Past `max_sessions`, a start is `busy`. A session's pod is deleted when it ends however it ends (its cap,
`end`, a reply that is no answer), and `PodLog.sweep` removes any a stopped app pod left behind. Logs carry the pod's
name, outcomes and durations, never an address or what the page held."""

import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from importlib import resources
from typing import Any

import httpx2

from .. import logs
from ..runs.kube_api import KubeApi, KubeError
from ..runs.loose import as_list, as_object
from ..runs.pod_log import PodLog
from . import driver
from .config import LooksConfig
from .pod_spec import SESSION_KEY_LABEL, SESSION_LABEL, session_manifest
from .session import REASONS, Acted, Act, BrowserSessions, Node, SessionUnavailable, Snapshot, Who

log = logging.getLogger("ashley.looks")
DRIVER = resources.files("ashley.looks").joinpath("driver.py").read_text()
REPLY_MARGIN_S = 5
"""How long past a step's own limit to wait for the pod's answer."""
ENDED = ("Succeeded", "Failed")


class KubernetesSessions(BrowserSessions):
    def __init__(self, api: KubeApi, http: httpx2.AsyncClient, namespace: str, runtime_class: str, image: str,
                 config: LooksConfig, token: Callable[[str], str],
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        """`token` gives the bearer token for the session pod of that name; the same name always gets the same token."""
        self._api = api
        self._http = http
        self._namespace = namespace
        self._runtime_class = runtime_class
        self._image = image
        self._config = config
        self._token = token
        self._sleep = sleep
        self._clock = clock
        self._pods = PodLog(api, namespace, SESSION_LABEL, config.log_bytes, config.poll_s, log, "looks.session", sleep,
                            clock, done="ended")

    def drives(self) -> bool:
        return True

    async def snapshot(self, who: Who) -> Snapshot:
        """Raises SessionUnavailable."""
        pod = await self._live(who)
        if pod is None:
            raise SessionUnavailable("no_session")
        return _snapshot(await self._ask(pod, "/snapshot", {}))

    async def act(self, who: Who, act: Act) -> Acted:
        """Raises SessionUnavailable. Logs `looks.session.started` with the pod and duration_ms when it starts one."""
        pod = await self._live(who)
        if pod is None:
            if act.action != "navigate":
                raise SessionUnavailable("no_session")
            pod = await self._start(who)
        body = {"action": act.action, "ref": act.ref, "text": act.text, "value": act.value, "url": act.url,
                "submit": act.submit}
        return _acted(await self._ask(pod, "/act", body))

    async def end(self, who: Who) -> bool:
        """Deletes every pod of `who`'s session."""
        names = [name for name, _ in await self._found(who)]
        for name in names:
            await self._end(name, "ended_by_her")
        return bool(names)

    async def _found(self, who: Who) -> list[tuple[str, str | None]]:
        """The pods of `who`'s session as (name, address, None until it has one) that are not over; a pod that is over
        is deleted."""
        pods = await self._listed(f"{SESSION_KEY_LABEL}={_key(who)}")
        found: list[tuple[str, str | None]] = []
        for pod in pods:
            name = str((as_object(pod.get("metadata")) or {}).get("name"))
            status = as_object(pod.get("status")) or {}
            if status.get("phase") in ENDED:
                await self._end(name, "pod_ended")
                continue
            ip = status.get("podIP")
            found.append((name, ip if isinstance(ip, str) and ip else None))
        return found

    async def _listed(self, selector: str) -> list[dict[str, Any]]:
        try:
            return await self._api.pods(self._namespace, selector)
        except KubeError as e:
            raise SessionUnavailable("unavailable") from e

    async def _live(self, who: Who) -> tuple[str, str] | None:
        """The session's pod as (name, address), or None when there is none, or it has no address yet."""
        for name, ip in await self._found(who):
            if ip is not None:
                return name, ip
        return None

    async def _start(self, who: Who) -> tuple[str, str]:
        started = self._clock()
        await self._pods.sweep(self._config.session_max_s + self._config.ready_timeout_s)
        running = [p for p in await self._listed(f"{SESSION_LABEL}=true")
                   if (as_object(p.get("status")) or {}).get("phase") not in ENDED]
        if len(running) >= self._config.max_sessions:
            raise SessionUnavailable("busy")
        name = f"session-{secrets.token_hex(6)}"
        manifest = session_manifest(name, _key(who), self._token(name), self._config, self._image,
                                    self._runtime_class, DRIVER)
        try:
            await self._api.create_pod(self._namespace, manifest)
        except KubeError as e:
            raise SessionUnavailable("unavailable") from e
        try:
            ip = await self._ready(who, name, started)
        except SessionUnavailable:
            await self._end(name, "never_ready")
            raise
        logs.info(log, "looks.session.started", pod=name, duration_ms=self._ms(started))
        return name, ip

    async def _ready(self, who: Who, name: str, started: float) -> str:
        """The pod's address once its page answers `/healthz`."""
        while self._clock() - started <= self._config.ready_timeout_s:
            for found, ip in await self._found(who):
                if found == name and ip is not None and await self._healthy(ip):
                    return ip
            await self._sleep(self._config.poll_s)
        raise SessionUnavailable("unavailable")

    async def _healthy(self, ip: str) -> bool:
        try:
            return (await self._http.get(_url(ip, "/healthz"), timeout=self._config.poll_s * 2)).status_code == 200
        except httpx2.HTTPError:
            return False

    async def _ask(self, pod: tuple[str, str], path: str, body: Mapping[str, object]) -> dict[str, Any]:
        """The pod's answer to `path`. A cap reached or an answer that is none ends the session: the pod is deleted."""
        name, ip = pod
        try:
            got = await self._http.post(_url(ip, path), json=body, headers={"Authorization": "Bearer " + self._token(name)},
                                        timeout=self._config.session_step_s + REPLY_MARGIN_S)
        except httpx2.HTTPError as e:
            await self._end(name, "unreachable")
            raise SessionUnavailable("unavailable") from e
        answer = _object(got)
        if got.status_code == 200 and answer is not None:
            return answer
        reason = None if answer is None else answer.get("reason")
        if got.status_code == 400 and isinstance(reason, str):
            raise SessionUnavailable(reason if reason in REASONS else "failed")
        if got.status_code == 410 and answer is not None and answer.get("ended") in ("time", "actions"):
            await self._end(name, str(answer["ended"]))
            raise SessionUnavailable("ended_" + str(answer["ended"]))
        await self._end(name, "bad_answer")
        raise SessionUnavailable("unavailable")

    async def _end(self, name: str, reason: str) -> None:
        try:
            await self._api.delete_pod(self._namespace, name)
        except KubeError as e:
            logs.warning(log, "looks.session.pod_left", pod=name, error=str(e))
            return
        logs.info(log, "looks.session.ended", pod=name, reason=reason)

    def _ms(self, started: float) -> int:
        return int((self._clock() - started) * 1000)


def _key(who: Who) -> str:
    return f"{who.household_id}-{who.conversation_id}"


def _url(ip: str, path: str) -> str:
    host = f"[{ip}]" if ":" in ip else ip
    return f"http://{host}:{driver.PORT}{path}"


def _object(got: httpx2.Response) -> dict[str, Any] | None:
    try:
        return as_object(got.json())
    except ValueError:
        return None


def _acted(answer: dict[str, Any]) -> Acted:
    seconds, actions = answer.get("seconds_left"), answer.get("actions_left")
    if type(seconds) is not int or type(actions) is not int:
        raise SessionUnavailable("failed")
    return Acted(seconds, actions)


def _snapshot(answer: dict[str, Any]) -> Snapshot:
    """The pod's snapshot, checked. Raises SessionUnavailable("failed") for one that is not."""
    acted = _acted(answer)
    nodes = as_list(answer.get("nodes"))
    url, title = answer.get("url"), answer.get("title")
    if nodes is None or not isinstance(url, str) or not isinstance(title, str):
        raise SessionUnavailable("failed")
    return Snapshot(url, title, tuple(_node(n) for n in nodes), answer.get("cut") is True, acted.seconds_left,
                    acted.actions_left)


def _node(raw: object) -> Node:
    node = as_object(raw)
    options = as_list(None if node is None else node.get("options")) or []
    if node is None or not all(isinstance(node.get(k), str) for k in ("ref", "role", "name")):
        raise SessionUnavailable("failed")
    return Node(node["ref"], node["role"], node["name"], node.get("secret") is True, node.get("disabled") is True,
                node.get("checked") is True, tuple(o for o in options if isinstance(o, str)))
