"""The Kubernetes browser sessions against a fake API and a fake pod: a first `navigate` makes a pod of its own carrying
the session's labels and token and waits for it to answer, any later call finds that pod by its labels, and the pod is
deleted however the session ends (its cap, `end`, a reply that is no answer, a pod that never came up)."""

import asyncio
import json
from dataclasses import replace
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import httpx2
import pytest
from ashley.looks import config, driver
from ashley.looks.kubernetes_session import DRIVER, KubernetesSessions
from ashley.looks.pod_spec import LABEL, SESSION_KEY_LABEL, SESSION_LABEL
from ashley.looks.session import Act, SessionUnavailable, Who
from ashley.runs.media_pod import FETCH_LABEL
from sandbox_support import Clock, FakeKube

T = TypeVar("T")
CONFIG = replace(config.load(), max_sessions=2)
IMAGE = "mcr.example/browser@sha256:" + "b" * 64
ME, THEM = Who(1, 10), Who(1, 11)
COUNTS = {"seconds_left": 590, "actions_left": 59}
SNAPSHOT = {"url": "https://shop.example/", "title": "Shop", "cut": False, **COUNTS,
            "nodes": [{"ref": "e0", "role": "button", "name": "Buy", "disabled": True},
                      {"ref": "e1", "role": "combobox", "name": "Size", "options": ["S", "L"]}]}


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def token(pod: str) -> str:
    return "token-of-" + pod


class Kube(FakeKube):
    """Pods are created Running with an address, and a listing honours its label selector."""

    def _create(self, namespace: str, manifest: dict[str, Any]) -> httpx2.Response:
        manifest["status"] = {"phase": "Running", "podIP": "10.1.2.3"}
        return super()._create(namespace, manifest)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        selector = request.url.params.get("labelSelector")
        if request.method == "GET" and selector and request.url.path.endswith("/pods"):
            wanted = dict(pair.split("=") for pair in selector.split(","))
            kept = [p for p in self.pods.values() if all(p["metadata"].get("labels", {}).get(k) == v for k, v in wanted.items())]
            return httpx2.Response(200, json={"items": kept})
        return super().handle(request)


class Pod:
    """What answers at the pod's address: `answers` by path as (status, body), a connection refused for the first
    `refuse` requests."""

    def __init__(self) -> None:
        self.answers: dict[str, tuple[int, Any]] = {"/healthz": (200, {}), "/snapshot": (200, SNAPSHOT),
                                                    "/act": (200, COUNTS)}
        self.refuse = 0
        self.dead = False
        self.seen: list[tuple[str, str, str, Any]] = []

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if self.dead or self.refuse > 0:
            self.refuse -= 1
            raise httpx2.ConnectError("refused")
        body = json.loads(request.content) if request.content else None
        self.seen.append((request.url.host, request.url.path, request.headers.get("Authorization", ""), body))
        status, answer = self.answers[request.url.path]
        return httpx2.Response(status, json=answer)


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.kube = Kube(tmp_path / "token")
        self.pod = Pod()
        self.clock = Clock()
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(self.pod.handle))
        self.sessions = KubernetesSessions(self.kube.api(), http, "ashley-sandbox", "gvisor", IMAGE, CONFIG, token,
                                           self.clock.sleep, self.clock)

    def started(self, who: Who = ME) -> str:
        run(self.sessions.act(who, Act("navigate", url="https://shop.example/")))
        return str(self.kube.created[-1]["metadata"]["name"])


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_a_first_navigate_makes_a_pod_of_its_own_and_asks_it_with_its_token(world: World) -> None:
    world.pod.refuse = 2
    done = run(world.sessions.act(ME, Act("navigate", url="https://shop.example/")))
    assert (done.seconds_left, done.actions_left) == (590, 59)
    (pod,) = world.kube.created
    name = pod["metadata"]["name"]
    labels = pod["metadata"]["labels"]
    assert labels == {SESSION_LABEL: "true", SESSION_KEY_LABEL: "1-10", FETCH_LABEL: "true"} and LABEL not in labels
    assert pod["spec"]["activeDeadlineSeconds"] == CONFIG.session_max_s + CONFIG.ready_timeout_s
    assert pod["spec"]["containers"][0]["command"][-1] == DRIVER
    env = {e["name"]: e["value"] for e in pod["spec"]["containers"][0]["env"]}
    assert env["ASHLEY_LOOK_TOKEN"] == token(name) and json.loads(env["ASHLEY_LOOK_LIMITS"])["session_max_s"] == 600
    host, path, auth, body = world.pod.seen[-1]
    assert (host, path, auth) == ("10.1.2.3", "/act", "Bearer " + token(name))
    assert body == {"action": "navigate", "ref": None, "text": None, "value": None, "url": "https://shop.example/",
                    "submit": False}
    assert world.clock.now > 0 and world.kube.deleted == []


def test_a_later_call_finds_the_pod_by_its_labels_and_reads_the_snapshot(world: World) -> None:
    name = world.started()
    seen = run(world.sessions.snapshot(ME))
    assert world.pod.seen[-1][:3] == ("10.1.2.3", "/snapshot", "Bearer " + token(name))
    assert (seen.url, seen.title, seen.cut, seen.seconds_left, seen.actions_left) == ("https://shop.example/", "Shop", False, 590, 59)
    assert [(n.ref, n.role, n.name, n.disabled, n.options) for n in seen.nodes] == [
        ("e0", "button", "Buy", True, ()), ("e1", "combobox", "Size", False, ("S", "L"))]
    assert len(world.kube.created) == 1


def test_another_conversation_has_no_session_and_a_step_other_than_navigate_starts_none(world: World) -> None:
    world.started()
    with pytest.raises(SessionUnavailable, match="no_session"):
        run(world.sessions.snapshot(THEM))
    with pytest.raises(SessionUnavailable, match="no_session"):
        run(world.sessions.act(THEM, Act("click", ref="e0")))
    assert len(world.kube.created) == 1


def test_a_cap_reached_deletes_the_pod_and_says_which(world: World) -> None:
    name = world.started()
    world.pod.answers["/act"] = (410, {"ended": "actions"})
    with pytest.raises(SessionUnavailable, match="ended_actions"):
        run(world.sessions.act(ME, Act("click", ref="e0")))
    assert world.kube.deleted == [name]
    with pytest.raises(SessionUnavailable, match="no_session"):
        run(world.sessions.snapshot(ME))


@pytest.mark.parametrize(("sent", "told"), [("stale_ref", "stale_ref"), ("secret_field", "secret_field"),
                                            ("something the pod invented", "failed")])
def test_a_step_the_page_refused_says_why_and_the_session_goes_on(world: World, sent: str, told: str) -> None:
    world.started()
    world.pod.answers["/act"] = (400, {"reason": sent})
    with pytest.raises(SessionUnavailable, match=told):
        run(world.sessions.act(ME, Act("click", ref="e0")))
    assert world.kube.deleted == []


@pytest.mark.parametrize("answer", [(200, ["not", "an", "object"]), (500, {}), (410, {"ended": "never"})])
def test_an_answer_that_is_no_answer_ends_the_session(world: World, answer: tuple[int, Any]) -> None:
    name = world.started()
    world.pod.answers["/act"] = answer
    with pytest.raises(SessionUnavailable, match="unavailable"):
        run(world.sessions.act(ME, Act("click", ref="e0")))
    assert world.kube.deleted == [name]


def test_counts_that_are_not_numbers_are_a_failure_and_the_session_goes_on(world: World) -> None:
    world.started()
    world.pod.answers["/act"] = (200, {"seconds_left": "soon", "actions_left": 1})
    with pytest.raises(SessionUnavailable, match="failed"):
        run(world.sessions.act(ME, Act("click", ref="e0")))
    assert world.kube.deleted == []


def test_a_pod_that_stops_answering_ends_the_session(world: World) -> None:
    name = world.started()
    world.pod.dead = True
    with pytest.raises(SessionUnavailable, match="unavailable"):
        run(world.sessions.snapshot(ME))
    assert world.kube.deleted == [name]


def test_a_pod_that_never_answers_its_health_check_is_deleted(world: World) -> None:
    world.pod.refuse = 10**6
    with pytest.raises(SessionUnavailable, match="unavailable"):
        run(world.sessions.act(ME, Act("navigate", url="https://shop.example/")))
    assert world.kube.deleted == [world.kube.created[0]["metadata"]["name"]]
    assert CONFIG.ready_timeout_s < world.clock.now < CONFIG.ready_timeout_s + 2 * CONFIG.poll_s + 1


def test_at_most_max_sessions_run_at_once_and_an_ended_one_does_not_count(world: World) -> None:
    world.started(Who(1, 1))
    first = world.started(Who(1, 2))
    with pytest.raises(SessionUnavailable, match="busy"):
        world.started(Who(1, 3))
    assert len(world.kube.created) == 2
    world.kube.pods[first]["status"]["phase"] = "Succeeded"
    world.started(Who(1, 3))
    assert len(world.kube.created) == 3


def test_a_pod_that_ended_by_itself_is_deleted_and_is_no_session(world: World) -> None:
    name = world.started()
    world.kube.pods[name]["status"]["phase"] = "Failed"
    with pytest.raises(SessionUnavailable, match="no_session"):
        run(world.sessions.snapshot(ME))
    assert world.kube.deleted == [name]


def test_end_deletes_the_pod_and_says_whether_there_was_one(world: World) -> None:
    name = world.started()
    assert run(world.sessions.end(ME)) is True and world.kube.deleted == [name]
    assert run(world.sessions.end(ME)) is False


def test_a_pod_a_stopped_app_pod_left_behind_is_swept_when_the_next_session_starts(world: World) -> None:
    world.kube.pods["session-old"] = {"metadata": {"name": "session-old", "creationTimestamp": "2000-01-01T00:00:00Z",
                                                   "labels": {SESSION_LABEL: "true"}},
                                      "status": {"phase": "Running", "podIP": "10.9.9.9"}}
    world.started()
    assert world.kube.deleted == ["session-old"]


def test_a_pod_the_api_refuses_is_unavailable_and_leaves_nothing(world: World) -> None:
    world.kube.fail = lambda request: 403 if request.method == "POST" else None
    with pytest.raises(SessionUnavailable, match="unavailable"):
        run(world.sessions.act(ME, Act("navigate", url="https://shop.example/")))
    assert world.kube.created == [] and world.pod.seen == []


def test_the_driver_the_pod_runs_is_the_drivers_own_text() -> None:
    assert DRIVER.startswith('"""The program a browser session') and driver.PORT == 8080
