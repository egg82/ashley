"""The podman sandbox's command line: the container is cut off as the pod is (no network, read-only root, no
capabilities, user 65534, the profile's limits), and the job's variables are named on it, never valued, since a process
listing shows every argument."""

from pathlib import Path

import pytest
from ashley.runs import config
from ashley.runs.model import Job
from ashley.runs.pod_spec import manifest
from ashley.runs.podman import RUNNER, PodmanSandbox, cpus, host_environment, memory

IMAGE = "registry.example/cad@sha256:" + "0" * 64


def test_the_container_is_cut_off_and_its_variables_are_named_not_valued() -> None:
    runs = config.load().with_image("build123d", IMAGE)
    job = Job("run-7", "build123d", "print('secret-ish script')", files={"a.txt": "x"})
    container = manifest(job, runs, RUNNER, "gvisor")["spec"]["containers"][0]
    env = {str(e["name"]): str(e["value"]) for e in container["env"]}
    profile = runs.profile("build123d")
    assert profile is not None
    argv = PodmanSandbox(runs).arguments(job.name, profile, env, container["command"], Path("/tmp/inputs-dir"))
    joined = " ".join(argv)
    assert "--volume /tmp/inputs-dir:/work/inputs:ro" in joined
    for flag in ("--network none", "--read-only", "--user 65534:65534", "--cap-drop ALL", "--memory 1g", "--cpus 1"):
        assert flag in joined
    assert len(env) >= 4 and all(f"--env {name}" in joined for name in env)
    assert not any(value in joined for value in env.values() if len(value) > 8)
    assert argv[argv.index(IMAGE) + 1:] == container["command"]


def test_kubernetes_quantities_become_podman_ones() -> None:
    assert (memory("256Mi"), memory("1Gi"), cpus("500m"), cpus("1")) == ("256m", "1g", "0.5", "1")


def test_podman_gets_the_socket_it_is_pointed_at_and_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTAINER_HOST", "unix:///run/user/1000/podman/podman.sock")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-job")
    found = host_environment()
    assert found["CONTAINER_HOST"] == "unix:///run/user/1000/podman/podman.sock"
    assert "ANTHROPIC_API_KEY" not in found
