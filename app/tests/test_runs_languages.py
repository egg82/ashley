"""The Sandbox's language profiles (`ashley.runs.config.Profile`, `runs.json` `languages`): build123d is a second
profile of the one Sandbox, run in the image the app is given, under the same security as a Python run; given no image
it is not run, never run in the Python image."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ashley import services
from ashley.inference.model import ToolCall
from ashley.runs import config
from ashley.runs.config import Profile, RunsConfig
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.model import Job
from ashley.runs.pod_spec import manifest
from ashley.runs.sandbox import Sandbox, SandboxUnavailable
from ashley.tools.run_code import NAME, RunCodeTools
from ashley.workshop import commands
from ashley.workshop.model import HER as HER_BY
from ashley.workshop.model import Owner
from ashley.workshop.run_piece import CannotRun, run_piece
from sandbox_support import CONFIG as PYTHON_ONLY
from sandbox_support import PYTHON, Clock, FakeKube, Script

CAD = "registry.test/apps/ashley-cad@sha256:" + "c" * 64
PROFILE = Profile("", 60, 120, "1", "500m", "1Gi", 32, 4096)
BOTH: RunsConfig = replace(PYTHON_ONLY, languages={"python": PYTHON, "build123d": replace(PROFILE, image=CAD)})
UNIMAGED: RunsConfig = replace(PYTHON_ONLY, languages={"python": PYTHON, "build123d": PROFILE})
PY_JOB = Job("run-1", "python", "print(1)")
CAD_JOB = Job("run-2", "build123d", "show(Box(1, 1, 1))")


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token")


def shipped() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(config.FILE.read_text())
    return loaded


def box(fake: FakeKube, runs: RunsConfig, clock: Clock | None = None) -> KubernetesSandbox:
    clock = clock or Clock()
    return KubernetesSandbox(fake.api(), runs, "ashley-sandbox", "gvisor", sleep=clock.sleep, clock=clock)


def test_the_shipped_build123d_profile_is_60_seconds_one_cpu_and_a_gibibyte_with_no_image() -> None:
    loaded = config.load()
    assert loaded.languages["build123d"] == Profile("", 60, 120, "1", "500m", "1Gi", 32, 8 * 1024 * 1024, 16 * 1024 * 1024, 16 * 1024 * 1024)
    assert loaded.offered() == ("python",) and loaded.profile("build123d") is None


def test_the_python_profile_is_its_entry_under_languages() -> None:
    assert PYTHON_ONLY.profile("python") == Profile(PYTHON.image, 10, 30, "500m", "250m", "256Mi", 32, 4096)


def test_an_image_given_makes_the_language_offered_after_python() -> None:
    assert BOTH.offered() == ("python", "build123d") and UNIMAGED.offered() == ("python",)
    assert config.load().with_image("build123d", CAD).profile("build123d") == replace(
        config.load().languages["build123d"], image=CAD)


@pytest.mark.parametrize("image", ["", "registry.test/ashley-cad:latest", "x@sha256:" + "C" * 64])
def test_an_image_not_pinned_by_digest_is_refused(image: str) -> None:
    with pytest.raises(ValueError):
        config.load().with_image("build123d", image)


def test_a_language_with_no_profile_cannot_be_given_an_image() -> None:
    with pytest.raises(ValueError):
        PYTHON_ONLY.with_image("build123d", CAD)


@pytest.mark.parametrize("change", [
    {"python": shipped()["languages"]["build123d"]},
    {"python": {k: v for k, v in shipped()["languages"]["python"].items() if k != "image"}},
    {"ruby": {"script_timeout_s": 1}},
    {"build123d": {**shipped()["languages"]["build123d"], "image": CAD}},
    {"build123d": {**shipped()["languages"]["build123d"], "pod_deadline_s": 60}},
    {"build123d": {**shipped()["languages"]["build123d"], "log_bytes": 50_000}},
    {"build123d": {**shipped()["languages"]["build123d"], "memory": ""}},
    {"build123d": {**shipped()["languages"]["build123d"], "cpu_request": 5}},
    {"build123d": {k: v for k, v in shipped()["languages"]["build123d"].items() if k != "cpu"}},
])
def test_a_bad_languages_entry_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        config.parse({**shipped(), "languages": {**shipped()["languages"], **change}})


def test_languages_that_are_a_list_are_refused() -> None:
    with pytest.raises(ValueError):
        config.parse({**shipped(), "languages": []})


def test_python_is_required_under_languages() -> None:
    without = {**shipped(), "languages": {"build123d": shipped()["languages"]["build123d"]}}
    with pytest.raises(ValueError):
        config.parse(without)


def test_the_build123d_pod_has_the_code_run_pods_security_and_its_own_image_and_limits() -> None:
    py, cad = manifest(PY_JOB, BOTH, "r", "gvisor")["spec"], manifest(CAD_JOB, BOTH, "r", "gvisor")["spec"]
    own = ("activeDeadlineSeconds", "containers", "volumes")
    assert {k: v for k, v in cad.items() if k not in own} == {k: v for k, v in py.items() if k not in own}
    one, two = cad["containers"][0], py["containers"][0]
    assert {k: v for k, v in one.items() if k not in ("image", "resources", "env")} == {
        k: v for k, v in two.items() if k not in ("image", "resources", "env")}
    assert one["image"] == CAD and two["image"] == PYTHON.image
    assert cad["activeDeadlineSeconds"] == 120
    assert one["resources"] == {"requests": {"cpu": "500m", "memory": "1Gi"}, "limits": {"cpu": "1", "memory": "1Gi"}}
    limits = json.loads(next(e["value"] for e in one["env"] if e["name"] == "ASHLEY_LIMITS"))
    assert limits["timeout_s"] == 60 and limits["log_bytes"] == 4096
    assert [v["emptyDir"]["sizeLimit"] for v in cad["volumes"]] == ["32Mi", "32Mi"]


def test_a_pod_for_a_language_not_run_is_not_made() -> None:
    with pytest.raises(ValueError):
        manifest(CAD_JOB, UNIMAGED, "r", "gvisor")


def test_the_sandbox_runs_a_build123d_job_in_the_cad_image(fake: FakeKube) -> None:
    sandbox = box(fake, BOTH)
    assert sandbox.languages() == ("python", "build123d")
    assert asyncio.run(sandbox.run(CAD_JOB)).outcome == "ran"
    assert fake.created[0]["spec"]["containers"][0]["image"] == CAD


def test_without_an_image_a_build123d_job_is_unavailable_and_no_pod_is_made(fake: FakeKube) -> None:
    sandbox = box(fake, UNIMAGED)
    assert sandbox.languages() == ("python",)
    with pytest.raises(SandboxUnavailable):
        asyncio.run(sandbox.run(CAD_JOB))
    assert fake.created == [] and fake.deleted == []


def test_a_build123d_pod_is_waited_for_by_its_own_deadline(fake: FakeKube) -> None:
    fake.script = Script(phases=["Running"])
    clock = Clock()
    out = asyncio.run(box(fake, BOTH, clock).run(CAD_JOB))
    assert out.outcome == "timed_out" and 120 < clock.now < 120 + 30
    fake.script = Script(phases=["Running"])
    clock = Clock()
    asyncio.run(box(fake, BOTH, clock).run(PY_JOB))
    assert 30 < clock.now < 60


def test_the_sweep_waits_for_the_longest_deadline_so_a_running_build123d_pod_is_not_taken(fake: FakeKube) -> None:
    age = (datetime.now(UTC) - timedelta(seconds=100)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake.leftover("run-9", age)
    asyncio.run(box(fake, BOTH).run(PY_JOB))
    assert "run-9" not in fake.deleted
    asyncio.run(box(fake, PYTHON_ONLY).run(PY_JOB))
    assert "run-9" in fake.deleted


def test_loose_run_code_offers_and_runs_python_only(fake: FakeKube) -> None:
    services.register(Sandbox, box(fake, BOTH))
    tools = RunCodeTools(10, 20, 30)
    spec = asyncio.run(tools.catalogue()).specs[0]
    assert json.dumps(spec.parameters["properties"]).count('"enum": ["python"]') == 1
    got = asyncio.run(tools.call(ToolCall("c1", NAME, {"language": "build123d", "script": "x"})))
    assert got.is_error and got.content.startswith("bad_arguments") and fake.created == []


def test_a_bench_run_in_build123d_is_refused_as_a_language_the_sandbox_does_not_run(fake: FakeKube) -> None:
    services.register(Sandbox, box(fake, UNIMAGED))
    with pytest.raises(CannotRun) as caught:
        asyncio.run(run_piece(Owner(1, 1), 1, commands.Run(HER_BY, 1, 1, "build123d")))
    assert caught.value.why == "language" and fake.created == []
