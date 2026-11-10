"""Support for the blind code-run tests: jobs, the pod-isolation checker, a KubernetesSandbox over the fake Kubernetes
API with a clock the fake sleep moves, and a Run-code world over a real Postgres."""

import asyncio
import base64
import copy
from collections.abc import Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ashley.runs.config import RunsConfig
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.model import Job
from sandbox_support import CONFIG, Clock, FakeKube, Script

MAX_SLEEPS = 2_000
FORBIDDEN_VOLUMES = ("hostPath", "configMap", "secret", "projected", "persistentVolumeClaim", "downwardAPI", "csi",
                     "nfs", "iscsi", "image")


def run[T](scenario: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(scenario, 30))


def job(name: str = "run-1", script: str = "print(1)", stdin: str = "", files: dict[str, str] | None = None) -> Job:
    return Job(name, "python", script, stdin, files or {})


def decoded(entry: dict[str, str]) -> str:
    """A job value as the container receives it: base64 of its UTF-8, so Kubernetes expands nothing in it."""
    return base64.b64decode(entry["value"], validate=True).decode("utf-8")


def container(manifest: dict[str, Any]) -> dict[str, Any]:
    containers: list[dict[str, Any]] = manifest["spec"]["containers"]
    assert len(containers) == 1
    return containers[0]


NAMESPACE = "ashley-sandbox"
RUNTIME = "gvisor"


def skeleton(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest without the job's values: what must be the same whatever the script, input or files say."""
    shape = copy.deepcopy(manifest)
    del container(shape)["env"]
    return shape


def check_isolated(manifest: dict[str, Any], config: RunsConfig) -> None:
    """Every isolation property of the contract, read from the pod as the Kubernetes API will take it."""
    assert manifest["kind"] == "Pod"
    assert manifest["metadata"].get("namespace", NAMESPACE) == NAMESPACE
    spec = manifest["spec"]
    python = config.languages["python"]
    assert spec["runtimeClassName"] == RUNTIME
    assert spec["automountServiceAccountToken"] is False
    for key in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace"):
        assert not spec.get(key, False), key
    assert spec["restartPolicy"] == "Never"
    assert spec["activeDeadlineSeconds"] == python.pod_deadline_s
    for key in ("initContainers", "ephemeralContainers", "nodeName"):
        assert not spec.get(key), key
    one = container(manifest)
    assert one["image"] == python.image
    context = one["securityContext"]
    assert not context.get("privileged", False)
    assert context["allowPrivilegeEscalation"] is False
    assert context["runAsNonRoot"] is True
    assert context["readOnlyRootFilesystem"] is True
    assert not context.get("capabilities", {}).get("add")
    assert context.get("runAsUser", 1) != 0
    assert one["resources"]["limits"] == {"cpu": python.cpu, "memory": python.memory}
    assert one["resources"]["requests"] == {"cpu": python.cpu_request, "memory": python.memory}
    assert "envFrom" not in one and not one.get("ports") and not one.get("volumeDevices")
    for entry in one["env"]:
        assert set(entry) == {"name", "value"} and isinstance(entry["value"], str)
    volumes: list[dict[str, Any]] = spec.get("volumes", [])
    for volume in volumes:
        assert set(volume) == {"name", "emptyDir"}, volume
        assert volume["emptyDir"].get("sizeLimit")
        assert not volume["emptyDir"].get("medium")
    assert {mount["name"] for mount in one.get("volumeMounts", [])} <= {volume["name"] for volume in volumes}


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
    config: RunsConfig = CONFIG
    sandbox: KubernetesSandbox = field(init=False)

    def __post_init__(self) -> None:
        self.sandbox = KubernetesSandbox(self.kube.api(), self.config, NAMESPACE, RUNTIME, self.clock.sleep, self.clock)


def rig(tmp_path: Path, script: Script | None = None, config: RunsConfig = CONFIG) -> Rig:
    return Rig(FakeKube(tmp_path / "token", script or Script()), Capped(), config)
