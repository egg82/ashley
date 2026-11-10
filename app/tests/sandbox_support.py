"""A fake Kubernetes API for the sandbox's contract tests, served through httpx2's MockTransport so `KubeApi` runs its
real HTTP code: pods are created, listed, read, logged and deleted in memory. Each created pod plays the `Script` it
was given: the phases its reads report in turn (the last repeats), its status once finished, and its log."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2
from ashley.runs.config import Profile, RunsConfig
from ashley.runs.kube_api import KubeApi
from ashley.runs.runner import MARK

TOKEN = "token-one"
PYTHON = Profile(image="docker.io/library/python:3.13.18-alpine3.24@sha256:" + "a" * 64, script_timeout_s=10,
                 pod_deadline_s=30, cpu="500m", cpu_request="250m", memory="256Mi", work_mib=32, log_bytes=4096)
CONFIG = RunsConfig(max_script_chars=200, max_stdin_chars=200,
                    output_chars=50, file_chars=40, max_files=2, poll_s=0.5, languages={"python": PYTHON})


def envelope_line(exit_code: int | None = 0, stdout: str = "", stderr: str = "", timed_out: bool = False,
                  files: dict[str, str] | None = None, cut: bool = False) -> str:
    return MARK + json.dumps({"exit_code": exit_code, "timed_out": timed_out, "stdout": stdout, "stderr": stderr,
                              "cut": cut, "files": files or {}, "skipped": []})


@dataclass
class Script:
    phases: list[str] = field(default_factory=lambda: ["Pending", "Running", "Succeeded"])
    log: str = field(default_factory=envelope_line)
    reason: str | None = None
    terminated: str | None = None
    log_status: int = 200


@dataclass
class FakeKube:
    token_file: Path
    script: Script = field(default_factory=Script)
    created: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    deleted: list[str] = field(default_factory=lambda: list[str]())
    pods: dict[str, dict[str, Any]] = field(default_factory=lambda: dict[str, dict[str, Any]]())
    reads: dict[str, int] = field(default_factory=lambda: dict[str, int]())
    tokens: list[str] = field(default_factory=lambda: list[str]())
    fail: Callable[[httpx2.Request], int | None] = lambda request: None

    def api(self) -> KubeApi:
        self.token_file.write_text(TOKEN)
        client = httpx2.AsyncClient(base_url="https://kube.test", transport=httpx2.MockTransport(self.handle))
        return KubeApi(client, str(self.token_file))

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.tokens.append(request.headers.get("Authorization", ""))
        refused = self.fail(request)
        if refused is not None:
            return httpx2.Response(refused, json={"message": "no"})
        parts = request.url.path.strip("/").split("/")
        if parts[:3] != ["api", "v1", "namespaces"] or parts[4] != "pods":
            return httpx2.Response(404)
        namespace, rest = parts[3], parts[5:]
        if request.method == "POST" and not rest:
            return self._create(namespace, json.loads(request.content))
        if request.method == "GET" and not rest:
            return httpx2.Response(200, json={"items": list(self.pods.values())})
        name = rest[0]
        if name not in self.pods:
            return httpx2.Response(404, json={"message": "not found"})
        if request.method == "DELETE":
            self.deleted.append(name)
            del self.pods[name]
            return httpx2.Response(200, json={})
        if rest[1:] == ["log"]:
            return httpx2.Response(self.script.log_status, content=self.script.log.encode())
        return httpx2.Response(200, json=self._read(name))

    def _create(self, namespace: str, manifest: dict[str, Any]) -> httpx2.Response:
        manifest["metadata"]["namespace"] = namespace
        manifest["metadata"].setdefault("creationTimestamp", "2099-01-01T00:00:00Z")
        self.created.append(manifest)
        self.pods[manifest["metadata"]["name"]] = manifest
        return httpx2.Response(201, json=manifest)

    def _read(self, name: str) -> dict[str, Any]:
        seen = self.reads.get(name, 0)
        self.reads[name] = seen + 1
        phase = self.script.phases[min(seen, len(self.script.phases) - 1)]
        status: dict[str, Any] = {"phase": phase}
        if phase in ("Succeeded", "Failed"):
            if self.script.reason:
                status["reason"] = self.script.reason
            if self.script.terminated:
                status["containerStatuses"] = [{"state": {"terminated": {"reason": self.script.terminated}}}]
        return {**self.pods[name], "status": status}

    def leftover(self, name: str, created: str) -> None:
        """A pod a stopped app pod left behind, created at `created`."""
        self.pods[name] = {"metadata": {"name": name, "creationTimestamp": created,
                                        "labels": {"ashley.yggdrasil.pub/run": "true"}}}


class Clock:
    """A clock the fake sleep moves on."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
