"""The pod a run gets is the pod `origin/main` made before python became a profile under `languages`:
`runs_pod_specs_main.json` was captured by running that code through `KubernetesSandbox` and the fake API, and is not
edited by hand. A pod is made again here by the same path and must equal it."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ashley.runs.config import Profile
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.model import Job
from sandbox_support import CONFIG, PYTHON, Clock, FakeKube

CAD = "registry.test/apps/ashley-cad@sha256:" + "c" * 64
BUILD123D = Profile(CAD, 60, 120, "1", "500m", "1Gi", 32, 4096, 1024)
CAPTURED: dict[str, Any] = json.loads(Path(__file__).with_name("runs_pod_specs_main.json").read_text())
PYTHON_JOB = Job("run-7", "python", "print(1)", stdin="the input", files={"data.csv": "a,b\n1,2\n", "b.txt": "x"})
CAD_JOB = Job("run-8", "build123d", "show(Box(1, 1, 1))")


def made(tmp_path: Path, job: Job) -> dict[str, Any]:
    fake, clock = FakeKube(tmp_path / "token"), Clock()
    runs = replace(CONFIG, languages={"python": PYTHON, "build123d": BUILD123D})
    asyncio.run(KubernetesSandbox(fake.api(), runs, "ashley-sandbox", "gvisor", sleep=clock.sleep, clock=clock).run(job))
    assert len(fake.created) == 1
    return fake.created[0]


def test_the_python_pod_is_the_one_main_made(tmp_path: Path) -> None:
    assert made(tmp_path, PYTHON_JOB) == CAPTURED["python"]


def test_the_build123d_pod_is_the_one_main_made(tmp_path: Path) -> None:
    assert made(tmp_path, CAD_JOB) == CAPTURED["build123d"]
