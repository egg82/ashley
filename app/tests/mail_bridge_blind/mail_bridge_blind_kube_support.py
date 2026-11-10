"""The fake Kubernetes, the singleton's body and the keeper played by a thread, for the blind Bridge suite; the record,
routes and database are in `mail_bridge_blind_support`."""

import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import CancelledError
from typing import Any

from ashley import services
from ashley.mail import config as mail_config, proton_bridge_job, proton_pod
from ashley.mail.proton_bridge import KeeperAccess
from ashley.mail.proton_bridge_job import BridgeKeeping
from ashley.mail.proton_login import ProtonLogin
from ashley.mail.proton_login_http import KeeperLogin
from ashley.runs.kube_api import KubeApi, KubeError
import pytest
from mail_bridge_blind_support import ALIASES, IMAGE, NS, PUBLIC, SITE, Pod, World, config


def wire_login(world: World, keeper_url: str, cert: str, token: str) -> None:
    """The room's login relay to a keeper at `keeper_url`: an epoch of the record holding the token and certificate the
    relay reads."""
    world.begin(access=KeeperAccess(token, cert))
    services.register(ProtonLogin, KeeperLogin((keeper_url,), world.record(), 5.0))


# --- Kubernetes -----------------------------------------------------------------------------------------------------


class FakeKube(KubeApi):
    """Pods and secrets of the namespaces in dicts; `events` is every call as (monotonic time, verb, name)."""

    def __init__(self) -> None:
        self.pods_by_name: dict[str, dict[str, Any]] = {}
        self.secrets_by_name: dict[str, dict[str, Any]] = {}
        self.events: list[tuple[float, str, str]] = []
        self.created: list[dict[str, Any]] = []
        self.minted: list[str] = []
        self.namespaces: set[str] = set()
        self.fail_create: list[Exception] = []

    def at(self, verb: str) -> list[tuple[float, str]]:
        return [(t, n) for t, v, n in self.events if v == verb]

    def _note(self, verb: str, namespace: str, name: str) -> None:
        self.events.append((time.monotonic(), verb, name))
        self.namespaces.add(namespace)

    async def create_pod(self, namespace: str, manifest: dict[str, Any]) -> None:
        self._note("create_pod", namespace, manifest["metadata"]["name"])
        if self.fail_create:
            raise self.fail_create.pop(0)
        pod: dict[str, Any] = json.loads(json.dumps(manifest))
        pod["status"] = {"phase": "Running"}
        self.created.append(json.loads(json.dumps(manifest)))
        self.pods_by_name[manifest["metadata"]["name"]] = pod

    async def pod(self, namespace: str, name: str) -> dict[str, Any] | None:
        self._note("pod", namespace, name)
        found = self.pods_by_name.get(name)
        return None if found is None else json.loads(json.dumps(found))

    async def pods(self, namespace: str, selector: str) -> list[dict[str, Any]]:
        self._note("pods", namespace, selector)
        return [json.loads(json.dumps(p)) for p in self.pods_by_name.values()]

    async def log(self, namespace: str, name: str, limit_bytes: int) -> str:
        self._note("log", namespace, name)
        return ""

    async def delete_pod(self, namespace: str, name: str) -> bool:
        self._note("delete_pod", namespace, name)
        return self.pods_by_name.pop(name, None) is not None

    async def create_secret(self, namespace: str, name: str, labels: dict[str, str], data: dict[str, str]) -> None:
        self._note("create_secret", namespace, name)
        self.secrets_by_name[name] = {"metadata": {"name": name, "labels": labels}, "data": dict(data)}
        self.minted.append(data[proton_pod.TOKEN_KEY])

    async def secret(self, namespace: str, name: str) -> dict[str, str] | None:
        self._note("secret", namespace, name)
        found = self.secrets_by_name.get(name)
        return None if found is None else dict(found["data"])

    async def secrets(self, namespace: str, selector: str) -> list[str]:
        self._note("secrets", namespace, selector)
        return list(self.secrets_by_name)

    async def delete_secret(self, namespace: str, name: str) -> bool:
        self._note("delete_secret", namespace, name)
        return self.secrets_by_name.pop(name, None) is not None

    def add_pod(self, name: str, phase: str = "Running") -> None:
        name = ALIASES.get(name, name)
        self.pods_by_name[name] = {"metadata": {"name": name}, "spec": {"containers": [{"name": "bridge", "image": IMAGE}]},
                                   "status": {"phase": phase}}

    def end_pod(self, name: str | None, how: str) -> None:
        assert name is not None
        if how == "deleted":
            self.pods_by_name.pop(name, None)
        else:
            self.pods_by_name[name]["status"] = {"phase": how}

    def tokens_made(self) -> list[str]:
        """Every token minted, in the order the secrets were made."""
        return list(self.minted)

    def created_at(self) -> list[float]:
        return [t for t, _ in self.at("create_pod")]


class Running:
    """The singleton's body running on the app's loop for one test, as the lease would run it."""

    def __init__(self, world: World, kube: FakeKube, site: str = SITE, cfg: mail_config.MailConfig | None = None) -> None:
        self.world, self.kube = world, kube
        portal = world.client.portal
        assert portal is not None
        self.cfg = cfg or config()

        async def body() -> None:
            await proton_bridge_job.run(BridgeKeeping(world.record(), kube, NS, IMAGE, PUBLIC, site, self.cfg))

        self.future = portal.start_task_soon(body)

    def wait_for(self, until: Callable[[], bool], limit: float = 10.0) -> bool:
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            self.survived()
            if until():
                return True
            time.sleep(0.02)
        return until()

    def survived(self) -> None:
        if self.future.done() and not self.future.cancelled() and self.future.exception() is not None:
            raise AssertionError(f"the singleton's body raised: {self.future.exception()!r}")

    def stop(self) -> None:
        self.survived()
        self.future.cancel()
        try:
            self.future.result(timeout=5)
        except (CancelledError, KubeError):
            pass
        except TimeoutError:
            raise AssertionError("the body did not stop when cancelled") from None

    def __enter__(self) -> "Running":
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


class Keeping:
    """A keeper played by a thread: it heartbeats a pod every `every` seconds until the app refuses it or `stop()`,
    and remembers the first refusal's status and when it came."""

    def __init__(self, world: World, pod: Pod, every: float = 0.1) -> None:
        self.world, self.pod, self.every = world, pod, every
        self.refused: int | None = None
        self.refused_at = 0.0
        self.halt = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        while not self.halt.is_set():
            got = self.world.beat(self.pod)
            if got.status_code != 200:
                self.refused, self.refused_at = got.status_code, time.monotonic()
                return
            self.halt.wait(self.every)

    def stop(self) -> None:
        self.halt.set()
        self.thread.join(5)


def texts(caplog: pytest.LogCaptureFixture) -> str:
    out: list[str] = []
    for r in caplog.records:
        out.append(f"{r.name} {r.getMessage()} {getattr(r, 'fields', {})!r} {r.args!r} {r.exc_text or ''}")
    return "\n".join(out)
