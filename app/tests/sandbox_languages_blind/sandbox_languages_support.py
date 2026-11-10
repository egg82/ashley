"""Support for the blind language-profile tests: a config with a CAD image given, jobs in either language, a
KubernetesSandbox over the fake Kubernetes API with a clock the fake sleep moves, and the pod properties a profile sets."""

import asyncio
import base64
import copy
import json
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx2
from ashley import services
from ashley.conversations.model import NewTurn
from ashley.conversations.postgres import PostgresConversations
from ashley.db.pool import PoolDatabase
from ashley.runs.config import RunsConfig, parse
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.model import Job, Language, NewRun, Output
from ashley.live.events import Event, Watcher
from ashley.live.fanout import Subscription
from ashley.live.live import Live
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from ashley.workshop.commands import Add
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import POLICY, household, person, scalar
from sandbox_support import Clock, FakeKube, Script

CAD = "registry.test/apps/ashley-cad@sha256:" + "c" * 64
SHIPPED = Path(__file__).resolve().parents[2] / "ashley" / "runs" / "runs.json"
MAX_SLEEPS = 5_000


def run[T](scenario: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(scenario, 30))


def shipped_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SHIPPED.read_text())
    return data


def distinct_data() -> dict[str, Any]:
    """The shipped tunables with the build123d profile's work directory and log made unlike Python's, so a pod or a
    log read that took the wrong language's value shows."""
    data = shipped_data()
    data["languages"]["build123d"].update({"work_mib": 16, "log_bytes": 300_000})
    return data


def config(image: str = CAD) -> RunsConfig:
    """The distinct tunables, with `image` given to build123d (none when empty)."""
    made = parse(distinct_data())
    return made.with_image("build123d", image) if image else made


def python_only() -> RunsConfig:
    return config("")


def job(language: Language = "python", name: str = "run-1", script: str = "print(1)") -> Job:
    return Job(name, language, script, "", {})


def container(manifest: dict[str, Any]) -> dict[str, Any]:
    containers: list[dict[str, Any]] = manifest["spec"]["containers"]
    assert len(containers) == 1
    return containers[0]


def decoded_values(manifest: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for entry in container(manifest)["env"]:
        try:
            out.append(base64.b64decode(entry["value"], validate=True).decode("utf-8"))
        except ValueError:
            continue
    return out


def work_size_limit(manifest: dict[str, Any]) -> str:
    """The size limit of the volume mounted at /work."""
    mounts: list[dict[str, Any]] = container(manifest)["volumeMounts"]
    names = [mount["name"] for mount in mounts if mount["mountPath"] == "/work"]
    assert len(names) == 1
    volumes: list[dict[str, Any]] = manifest["spec"]["volumes"]
    found = [volume["emptyDir"]["sizeLimit"] for volume in volumes if volume["name"] == names[0]]
    assert len(found) == 1
    return str(found[0])


def check_isolated(manifest: dict[str, Any], cfg: RunsConfig, language: Language) -> None:
    """The isolation properties of the contract and the profile's own image, deadline and limits, read from the pod."""
    profile = cfg.profile(language)
    assert profile is not None
    assert manifest["kind"] == "Pod"
    spec = manifest["spec"]
    assert spec["runtimeClassName"] == cfg.runtime_class
    assert spec["automountServiceAccountToken"] is False
    for key in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace"):
        assert not spec.get(key, False), key
    assert spec["restartPolicy"] == "Never"
    assert spec["activeDeadlineSeconds"] == profile.pod_deadline_s
    for key in ("initContainers", "ephemeralContainers", "nodeName"):
        assert not spec.get(key), key
    one = container(manifest)
    assert one["image"] == profile.image
    context = one["securityContext"]
    assert not context.get("privileged", False)
    assert context["allowPrivilegeEscalation"] is False
    assert context["runAsNonRoot"] is True
    assert context["readOnlyRootFilesystem"] is True
    assert not context.get("capabilities", {}).get("add")
    assert context.get("runAsUser", 1) != 0
    assert one["resources"]["limits"] == {"cpu": profile.cpu, "memory": profile.memory}
    assert one["resources"]["requests"] == {"cpu": profile.cpu_request, "memory": profile.memory}
    assert "envFrom" not in one and not one.get("ports")
    volumes: list[dict[str, Any]] = spec.get("volumes", [])
    for volume in volumes:
        assert set(volume) == {"name", "emptyDir"}, volume
        assert volume["emptyDir"].get("sizeLimit")
    assert work_size_limit(manifest) == f"{profile.work_mib}Mi"


def without_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest minus everything a language profile sets and the job carries: what both languages share."""
    shape = copy.deepcopy(manifest)
    spec = shape["spec"]
    one = container(shape)
    for key in ("env", "image", "resources"):
        one.pop(key, None)
    spec.pop("activeDeadlineSeconds", None)
    for volume in spec.get("volumes", []):
        volume["emptyDir"].pop("sizeLimit", None)
    shape["metadata"].pop("name", None)
    return shape


class Capped(Clock):
    """The fake clock, failing a run that polls forever instead of hanging the suite."""

    def __init__(self) -> None:
        super().__init__()
        self.sleeps = 0

    async def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        assert self.sleeps < MAX_SLEEPS, "the sandbox polled forever"
        await super().sleep(seconds)


@dataclass
class Rig:
    kube: FakeKube
    clock: Capped
    cfg: RunsConfig
    sandbox: KubernetesSandbox = field(init=False)

    def __post_init__(self) -> None:
        self.sandbox = KubernetesSandbox(self.kube.api(), self.cfg, self.clock.sleep, self.clock)


def rig(tmp_path: Path, script: Script | None = None, cfg: RunsConfig | None = None) -> Rig:
    return Rig(FakeKube(tmp_path / "token", script or Script()), Capped(), cfg or config())


def log_limits(kube: FakeKube) -> list[str]:
    """Wraps nothing: installs a request hook on `kube` that records each pod-log read's byte limit."""
    seen: list[str] = []

    def watch(request: httpx2.Request) -> int | None:
        if request.url.path.endswith("/log"):
            seen.append(request.url.params.get("limitBytes", ""))
        return None

    kube.fail = watch
    return seen


@dataclass
class World:
    """A real Postgres with a household, a conversation and a person turn, and the Runs service over it."""

    url: str
    home: int
    conversation: int
    turn: int
    runs: PostgresRuns

    def new(self, language: Language, script: str = "print(1)") -> NewRun:
        return NewRun(self.home, self.conversation, self.turn, "call-1", language, script, "", {})


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        home = household(url)
        who = person(url, home)
        conversations = PostgresConversations(db, POLICY)
        conv = await conversations.for_thread(home, "t1", "chat", [who])
        turn = await conversations.add_turn(conv.id, NewTurn("person", "run it", who))
        yield World(url, home, conv.id, turn.id, PostgresRuns(db))
    finally:
        await db.close()


NOTE = Kind("note", "stored", "Note", 100, "plain")
CODE_KIND = Kind("code", "stored", "Code", 100, "code", "python")
RULES = Rules(MappingProxyType({"note": NOTE, "code": CODE_KIND}), max_pieces=5, title_max_chars=10, recent_commands=20,
              undo_window=100)


@dataclass
class Bench:
    """A real Workshop and Runs over one Postgres pool, and Alana's bench with one code piece."""

    url: str
    owner: Owner
    bench: int
    runs: PostgresRuns

    def turn(self) -> tuple[int, int]:
        conv = int(scalar(self.url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                          (self.owner.household_id,)))
        turn = int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                          "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conv, self.owner.household_id)))
        return conv, turn


@asynccontextmanager
async def bench(url: str, body: str = "box = 1") -> AsyncGenerator[Bench]:
    database = PoolDatabase(url)
    await database.open()
    home = household(url, "one")
    owner = Owner(home, person(url, home, "Alana"))
    workshop = PostgresWorkshop(database, RULES)
    runs = PostgresRuns(database)
    services.register(Workshop, workshop)
    services.register(Runs, runs)
    services.register(Live, Quiet())
    try:
        made = await workshop.open(owner, "b")
        await workshop.apply(owner, made.id, Add(By(owner.person_id), "code", Text("c", body), "small"))
        yield Bench(url, owner, made.id, runs)
    finally:
        for interface in (Workshop, Runs, Live):
            services.unregister(interface)
        await database.close()


class Quiet(Live):
    def publish(self, event: Event) -> None:
        return None

    def subscribe(self, viewer: Watcher) -> Subscription:
        raise NotImplementedError


GAVE = Output("ran", 0, "OUT-SL", "", False, {}, ())


@dataclass
class Recording(Sandbox):
    offers: tuple[Language, ...] = ("python", "build123d")
    jobs: list[Job] = field(default_factory=lambda: list[Job]())

    def languages(self) -> tuple[Language, ...]:
        return self.offers

    async def run(self, job: Job) -> Output:
        self.jobs.append(job)
        return GAVE
