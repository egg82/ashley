"""The sandbox's tunables (`ashley.runs.config`): the shipped file loads, its image is pinned by digest, and a file
that would let the pod outlive nothing, or run an unpinned image, is refused."""

import json
from typing import Any

import pytest
from ashley.runs import config


def shipped() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(config.FILE.read_text())
    return loaded


def test_the_shipped_file_loads_with_a_seconds_scale_deadline() -> None:
    loaded = config.load()
    python = loaded.languages["python"]
    assert "@sha256:" in python.image
    assert python.script_timeout_s < python.pod_deadline_s <= 60


def python(**change: object) -> dict[str, object]:
    languages: Any = shipped()["languages"]
    return {"python": {**languages["python"], **change}}


@pytest.mark.parametrize("change", [
    {"image": "docker.io/library/python:3.13-alpine"},
    {"image": "python@sha256:short"},
    {"image": "python@sha256:" + "A" * 64},
    {"image": "python@sha256:" + "a" * 64 + "x"},
    {"pod_deadline_s": 10},
    {"log_bytes": 50_000},
    {"script_timeout_s": 0},
    {"cpu": ""},
    {"extra": 1},
])
def test_a_bad_python_profile_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        config.parse({**shipped(), "languages": python(**change)})


@pytest.mark.parametrize("change", [{"poll_s": "fast"}, {"extra": 1}])
def test_a_bad_shared_key_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        config.parse({**shipped(), **change})


def test_a_missing_key_is_refused() -> None:
    data = shipped()
    del data["namespace"]
    with pytest.raises(ValueError):
        config.parse(data)


QUOTA_PODS = 4
QUOTA = {"requests.cpu": 1000, "limits.cpu": 2000, "requests.memory": 1024, "limits.memory": 2048}
"""The sandbox namespace's ResourceQuota, millicores and MiB (cluster repo, kustomization/ashley-sandbox/limits.yaml)."""


def milli(cpu: str) -> int:
    return int(cpu[:-1]) if cpu.endswith("m") else int(float(cpu) * 1000)


def mib(memory: str) -> int:
    assert memory.endswith("Mi")
    return int(memory[:-2])


def test_as_many_runs_as_the_quota_admits_pods_fit_its_totals_at_once() -> None:
    shipped = config.load().languages["python"]
    used = {"requests.cpu": milli(shipped.cpu_request), "limits.cpu": milli(shipped.cpu),
            "requests.memory": mib(shipped.memory), "limits.memory": mib(shipped.memory)}
    assert all(QUOTA_PODS * used[k] <= QUOTA[k] for k in QUOTA), used
    assert milli(shipped.cpu_request) <= milli(shipped.cpu)
