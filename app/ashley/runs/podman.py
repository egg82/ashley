"""A sandbox on this machine: each job in a podman container of its own, from the pod `pod_spec.manifest` would make
(the same image, environment, command and limits), with no network, a read-only root, no capabilities, user 65534 and
the two size-limited scratch directories; its output read from the container's stdout as a pod's log is read. A
container's name adds a random suffix to the job's, since two processes on one machine number their runs alike. For a
process off the cluster (an eval run on a workstation); it has no gVisor, so it runs only code its caller trusts as
much as its own. Logs `runs.sandbox` with the container's name, the outcome and duration_ms, never the script."""

import asyncio
import logging
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from importlib import resources

from .. import logs
from . import envelope
from .config import Profile, RunsConfig
from .model import Job, Language, Output
from .pod_spec import manifest
from .sandbox import Sandbox, SandboxUnavailable

log = logging.getLogger("ashley.runs")
RUNNER = resources.files("ashley.runs").joinpath("runner.py").read_text()
PODMAN_FAILED = 125
KILLED = 137
_HOST = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "XDG_RUNTIME_DIR", "CONTAINERS_CONF", "USER")}
"""What podman itself needs from this process's environment; nothing else of it reaches the job."""


class PodmanSandbox(Sandbox):
    def __init__(self, config: RunsConfig, podman: str = "podman") -> None:
        self._config = config
        self._podman = podman

    def languages(self) -> tuple[Language, ...]:
        return self._config.offered()

    async def run(self, job: Job) -> Output:
        """Raises SandboxUnavailable for a language it was given no image for, or when podman could not start the
        container. A container past the pod's deadline is killed and `timed_out`."""
        started = time.monotonic()
        profile = self._config.profile(job.language)
        if profile is None:
            raise SandboxUnavailable(f"{job.language} is not run")
        container = manifest(job, self._config, RUNNER, runtime_class="")["spec"]["containers"][0]
        env = {str(e["name"]): str(e["value"]) for e in container["env"]}
        name = f"ashley-{job.name}-{uuid.uuid4().hex[:8]}"
        output = await self._ran(name, self.arguments(name, profile, env, container["command"]), env, profile)
        logs.info(log, "runs.sandbox", pod=job.name, outcome=output.outcome, exit_code=output.exit_code,
                  duration_ms=int((time.monotonic() - started) * 1000))
        return output

    def arguments(self, name: str, profile: Profile, env: Mapping[str, str], command: Sequence[str]) -> list[str]:
        """The job's variables are named here and handed through podman's own environment: a file of them would hold
        lines longer than podman reads."""
        scratch = f"rw,size={profile.work_mib}m,mode=1777"
        return [self._podman, "run", "--rm", "--name", name, "--network", "none", "--read-only",
                "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--memory", memory(profile.memory), "--cpus", cpus(profile.cpu), "--tmpfs", f"/work:{scratch}",
                "--tmpfs", f"/out:{scratch}", "--workdir", "/work", *(a for n in env for a in ("--env", n)),
                profile.image, *command]

    async def _ran(self, name: str, arguments: list[str], env: Mapping[str, str], profile: Profile) -> Output:
        try:
            proc = await asyncio.create_subprocess_exec(*arguments, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.DEVNULL, env={**_HOST, **env})
        except OSError as e:
            logs.warning(log, "runs.sandbox", pod=name, outcome="unavailable", error=type(e).__name__)
            raise SandboxUnavailable(type(e).__name__) from e
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), profile.pod_deadline_s)
        except TimeoutError:
            await (await asyncio.create_subprocess_exec(self._podman, "kill", name)).wait()
            return Output("timed_out", None, "", "")
        if proc.returncode == PODMAN_FAILED:
            logs.warning(log, "runs.sandbox", pod=name, outcome="unavailable", error="podman_failed")
            raise SandboxUnavailable("podman could not run the container")
        found = envelope.parse(out[:profile.log_bytes].decode("utf-8", "replace"), self._config, profile.artifact_bytes)
        if found is not None:
            return found
        return Output("out_of_memory" if proc.returncode == KILLED else "failed", None, "", "")


def memory(quantity: str) -> str:
    """A Kubernetes memory quantity (`256Mi`, `1Gi`) as podman takes it."""
    return quantity.replace("Gi", "g").replace("Mi", "m")


def cpus(quantity: str) -> str:
    """A Kubernetes CPU quantity (`1`, `500m`) as podman's `--cpus` takes it."""
    return str(int(quantity[:-1]) / 1000) if quantity.endswith("m") else quantity
