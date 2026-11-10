"""Shared pieces of the warm look pod's blind contract tests: a Kubernetes API that keeps pods in a dict, a cold looker
that plays pictures or failures, a Playwright of the public sync API whose browsers record what happened to them, and
a real HTTP server around `shooter.handler` with a worker thread standing for the thread that owns Playwright."""

import asyncio
import base64
import json
import logging
import queue
import threading
from collections.abc import Awaitable, Coroutine, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from typing import Any, Callable, TypeVar

import httpx2
import pytest
from ashley.looks import config as looks_config
from ashley.looks import shooter
from ashley.looks.kubernetes import KubernetesLooker
from ashley.looks.looker import LookUnavailable, Shot, Target
from ashley.looks.warm_pod import NAME, SPEC_ANNOTATION, WarmPod
from ashley.runs.kube_api import KubeApi, KubeError

T = TypeVar("T")

CONFIG = looks_config.load()
NS = "ashley-sandbox"
RUNTIME = "gvisor"
IMAGE = "registry.test/apps/ashley-look@sha256:" + "a" * 64
APP = "http://ashley.ashley.svc:8080"
PREFIX = APP + "/look/"
WARM_URL = "http://ashley-look-warm.ashley-sandbox.svc:8080"
SHOOTER_TEXT = "# the shooter program\nprint('shooter')\n"
TARGET = Target(household_id=1, person_id=2, bench_id=3, piece_id=None)
TOKEN = "TOKENzq9x7"
PAGE_URL = f"{PREFIX}{TOKEN}"
JPEG = bytes.fromhex("ffd8ff") + b"\xe0\x00\x10JFIF\x00warm-picture"
LIMITS: dict[str, int] = {"width": 1280, "height": 800, "max_height": 2400, "quality": 80, "max_bytes": 1000, "ready_s": 7}


def go(scenario: Coroutine[Any, Any, T], limit: float = 20.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def line_of(jpeg: bytes) -> str:
    return shooter.MARK + base64.b64encode(jpeg).decode()


def failed_line(reason: str) -> str:
    return shooter.FAILED + reason


def fields_of(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    out: list[str] = []
    for r in caplog.records:
        out.append(f"{r.getMessage()} {getattr(r, 'fields', {})!r} {r.args!r}")
        if r.exc_info:
            out.append(logging.Formatter().formatException(r.exc_info))
    return "\n".join(out)


def with_config(**changes: float | str) -> looks_config.LooksConfig:
    return replace(CONFIG, **changes)


# ---------------------------------------------------------------- Kubernetes

def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeKube(KubeApi):
    """Pods of one namespace in a dict. `calls` is every call in order; `fail` queues exceptions per verb; creating a
    pod whose name is taken fails as Kubernetes does (409), and `terminating` makes a delete leave the pod with a
    `deletionTimestamp` instead of removing it."""

    def __init__(self) -> None:
        self.pods_by_name: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.created: list[dict[str, Any]] = []
        self.fail: dict[str, list[Exception]] = {}
        self.terminating = False
        self.namespaces: set[str] = set()

    def _enter(self, verb: str, namespace: str, name: str) -> None:
        self.calls.append((verb, name))
        self.namespaces.add(namespace)
        if self.fail.get(verb):
            raise self.fail[verb].pop(0)

    def count(self, verb: str) -> int:
        return sum(1 for v, _ in self.calls if v == verb)

    async def create_pod(self, namespace: str, manifest: dict[str, Any]) -> None:
        name = manifest["metadata"]["name"]
        self._enter("create", namespace, name)
        if name in self.pods_by_name:
            raise KubeError("409")
        pod: dict[str, Any] = json.loads(json.dumps(manifest))
        pod["metadata"]["creationTimestamp"] = stamp(datetime.now(UTC))
        pod["status"] = {"phase": "Pending"}
        self.created.append(json.loads(json.dumps(manifest)))
        self.pods_by_name[name] = pod

    async def pod(self, namespace: str, name: str) -> dict[str, Any] | None:
        self._enter("get", namespace, name)
        found = self.pods_by_name.get(name)
        return None if found is None else json.loads(json.dumps(found))

    async def pods(self, namespace: str, selector: str) -> list[dict[str, Any]]:
        self._enter("list", namespace, selector)
        out: list[dict[str, Any]] = []
        for pod in self.pods_by_name.values():
            labels: dict[str, str] = pod["metadata"].get("labels", {})
            if all(_matches(labels, part) for part in selector.split(",")):
                out.append(json.loads(json.dumps(pod)))
        return out

    async def log(self, namespace: str, name: str, limit_bytes: int) -> str:
        self._enter("log", namespace, name)
        return ""

    async def delete_pod(self, namespace: str, name: str) -> bool:
        self._enter("delete", namespace, name)
        pod = self.pods_by_name.get(name)
        if pod is None:
            return False
        if self.terminating:
            pod["metadata"]["deletionTimestamp"] = stamp(datetime.now(UTC))
        else:
            del self.pods_by_name[name]
        return True

    def put(self, manifest: dict[str, Any], phase: str = "Running", age_s: float = 5.0) -> dict[str, Any]:
        """A pod as the cluster would hold it for `manifest`, `age_s` old."""
        pod: dict[str, Any] = json.loads(json.dumps(manifest))
        pod["metadata"]["creationTimestamp"] = stamp(datetime.now(UTC) - timedelta(seconds=age_s))
        pod["status"] = {"phase": phase}
        self.pods_by_name[pod["metadata"]["name"]] = pod
        return pod

    def warm(self) -> dict[str, Any] | None:
        return self.pods_by_name.get(NAME)


def _matches(labels: dict[str, str], term: str) -> bool:
    if "!=" in term:
        key, value = term.split("!=", 1)
        return labels.get(key) != value
    key, value = term.split("=", 1)
    return labels.get(key) == value


def keeper(kube: KubeApi, config: looks_config.LooksConfig = CONFIG, image: str = IMAGE,
           sleep: Callable[[float], Awaitable[None]] | None = None) -> WarmPod:
    async def no_sleep(seconds: float) -> None:
        await asyncio.sleep(0)

    return WarmPod(kube, NS, RUNTIME, image, PREFIX, SHOOTER_TEXT, config, sleep or no_sleep)


def annotation_of(pod: dict[str, Any]) -> str | None:
    value = pod["metadata"].get("annotations", {}).get(SPEC_ANNOTATION)
    return None if value is None else str(value)


# --------------------------------------------------------------- cold looker

class FakeCold(KubernetesLooker):
    """The per-look pod's looker, played: `outcome` is the picture it gives or the reason it raises."""

    def __init__(self, outcome: bytes | str = b"cold-picture", draws: bool = True) -> None:
        self.outcome = outcome
        self.draws = draws
        self.asked: list[tuple[str, Target]] = []

    def renders(self) -> bool:
        return self.draws

    def url(self, target: Target) -> str:
        return PAGE_URL

    async def look(self, name: str, target: Target) -> Shot:
        self.asked.append((name, target))
        if isinstance(self.outcome, str):
            raise LookUnavailable(self.outcome)
        return Shot(self.outcome)


def mock_client(handler: Callable[[httpx2.Request], httpx2.Response | Exception]) -> tuple[httpx2.AsyncClient, list[httpx2.Request]]:
    """An HTTP client whose pod is `handler`; an Exception it returns is raised as the transport would."""
    seen: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        out = handler(request)
        if isinstance(out, Exception):
            raise out
        return out

    return httpx2.AsyncClient(transport=httpx2.MockTransport(respond)), seen


def text_reply(body: str, status: int = 200) -> httpx2.Response:
    return httpx2.Response(status, text=body)


# --------------------------------------------------------------- HTTP server

Job = tuple[str, "queue.Queue[str]"]


@dataclass
class Pod:
    """A running warm pod: the real handler on a loopback port and a worker thread taking jobs through `answer`."""

    base: str
    jobs: "queue.Queue[Job]"
    gate: threading.Lock
    seen: list[str]

    def post(self, body: bytes | str, path: str = "/look", timeout: float = 10.0) -> httpx2.Response:
        return httpx2.post(self.base + path, content=body, timeout=timeout)

    def look(self, url: str) -> httpx2.Response:
        return self.post(json.dumps({"url": url}))


@contextmanager
def pod_server(prefix: str = PREFIX, wait_s: float = 5.0,
               answer: Callable[[str], str] | None = None, worker: bool = True) -> Generator[Pod]:
    jobs: queue.Queue[Job] = queue.Queue()
    gate = threading.Lock()
    server = ThreadingHTTPServer(("127.0.0.1", 0), shooter.handler(prefix, jobs, gate, wait_s))
    server.daemon_threads = True
    pod = Pod(f"http://127.0.0.1:{server.server_address[1]}", jobs, gate, [])
    stop = threading.Event()

    def work() -> None:
        while not stop.is_set():
            try:
                url, reply = jobs.get(timeout=0.05)
            except queue.Empty:
                continue
            pod.seen.append(url)
            reply.put(answer(url) if answer else line_of(JPEG))

    threads = [threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)]
    if worker:
        threads.append(threading.Thread(target=work, daemon=True))
    for t in threads:
        t.start()
    try:
        yield pod
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        for t in threads:
            t.join(2)
