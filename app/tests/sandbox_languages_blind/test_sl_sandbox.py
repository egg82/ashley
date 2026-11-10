"""KubernetesSandbox with language profiles: it runs the languages its config has an image for, each in its own image
and deadline, refuses the others before any pod, and never falls back to Python's image."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ashley.runs.model import Job
from ashley.runs.sandbox import SandboxUnavailable
from sandbox_languages_support import CAD, check_isolated, container, job, log_limits, python_only, rig, run
from sandbox_support import Script, envelope_line


def test_it_runs_python_alone_when_build123d_has_no_image(tmp_path: Path) -> None:
    assert rig(tmp_path, cfg=python_only()).sandbox.languages() == ("python",)


def test_it_runs_both_when_build123d_has_its_image(tmp_path: Path) -> None:
    assert rig(tmp_path).sandbox.languages() == ("python", "build123d")


def test_a_build123d_run_is_one_isolated_pod_in_the_cad_image_and_is_deleted(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(log=envelope_line(0, "model\n")))
    output = run(world.sandbox.run(job("build123d", "run-5")))
    assert (output.outcome, output.exit_code, output.stdout) == ("ran", 0, "model\n")
    assert [pod["metadata"]["name"] for pod in world.kube.created] == ["run-5"]
    check_isolated(world.kube.created[0], world.cfg, "build123d")
    assert container(world.kube.created[0])["image"] == CAD
    assert world.kube.deleted == ["run-5"] and world.kube.pods == {}


def test_a_python_run_beside_it_stays_in_the_python_image(tmp_path: Path) -> None:
    world = rig(tmp_path)
    run(world.sandbox.run(job("python", "run-1")))
    run(world.sandbox.run(job("build123d", "run-2")))
    run(world.sandbox.run(job("python", "run-3")))
    images = {pod["metadata"]["name"]: container(pod)["image"] for pod in world.kube.created}
    assert images == {"run-1": world.cfg.languages["python"].image, "run-2": CAD, "run-3": world.cfg.languages["python"].image}


def test_a_build123d_job_with_no_image_is_unavailable_before_any_pod(tmp_path: Path) -> None:
    world = rig(tmp_path, cfg=python_only())
    with pytest.raises(SandboxUnavailable):
        run(world.sandbox.run(job("build123d")))
    assert world.kube.created == [] and world.kube.pods == {}


def test_it_never_falls_back_to_the_python_image(tmp_path: Path) -> None:
    world = rig(tmp_path, cfg=python_only())
    with pytest.raises(SandboxUnavailable):
        run(world.sandbox.run(job("build123d")))
    assert [container(pod)["image"] for pod in world.kube.created] == []


def test_a_job_in_a_language_it_has_no_profile_for_is_unavailable_before_any_pod(tmp_path: Path) -> None:
    fields: dict[str, Any] = {"name": "run-1", "language": "cobol", "script": "x", "stdin": "", "files": {}}
    world = rig(tmp_path)
    with pytest.raises(SandboxUnavailable):
        run(world.sandbox.run(Job(**fields)))
    assert world.kube.created == []


def test_a_build123d_pod_never_started_is_unavailable_only_past_its_own_deadline(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    cad = rig(tmp_path / "a", Script(phases=["Pending"]))
    with pytest.raises(SandboxUnavailable):
        run(cad.sandbox.run(job("build123d")))
    assert cad.clock.now >= 120 and cad.kube.pods == {}
    python = rig(tmp_path / "b", Script(phases=["Pending"]))
    with pytest.raises(SandboxUnavailable):
        run(python.sandbox.run(job("python")))
    assert 30 <= python.clock.now < 120


def test_a_build123d_pod_still_running_after_python_s_deadline_is_waited_for(tmp_path: Path) -> None:
    phases = ["Pending"] + ["Running"] * 130 + ["Succeeded"]
    world = rig(tmp_path, Script(phases=phases, log=envelope_line(0, "done")))
    output = run(world.sandbox.run(job("build123d")))
    assert (output.outcome, output.stdout) == ("ran", "done")
    assert world.clock.now > 30


def test_each_run_reads_its_own_languages_log_limit(tmp_path: Path) -> None:
    world = rig(tmp_path)
    seen = log_limits(world.kube)
    run(world.sandbox.run(job("python", "run-1")))
    run(world.sandbox.run(job("build123d", "run-2")))
    assert seen == [str(world.cfg.languages["python"].log_bytes), "300000"]


def old_pod(world: Any, name: str, age_s: int) -> None:
    created = datetime.now(UTC) - timedelta(seconds=age_s)
    world.kube.leftover(name, created.strftime("%Y-%m-%dT%H:%M:%SZ"))


def test_a_pod_older_than_twice_the_longest_deadline_is_swept(tmp_path: Path) -> None:
    world = rig(tmp_path)
    old_pod(world, "run-old", 300)
    run(world.sandbox.run(job("python", "run-2")))
    assert "run-old" in world.kube.deleted


def test_a_pod_younger_than_that_is_kept_while_a_build123d_pod_may_still_run(tmp_path: Path) -> None:
    world = rig(tmp_path)
    old_pod(world, "run-cad", 100)
    run(world.sandbox.run(job("python", "run-2")))
    assert "run-cad" not in world.kube.deleted and "run-cad" in world.kube.pods


def test_the_sweep_waits_twice_the_longest_deadline_even_when_the_longest_is_not_run(tmp_path: Path) -> None:
    world = rig(tmp_path, cfg=python_only())
    old_pod(world, "run-cad", 100)
    run(world.sandbox.run(job("python", "run-2")))
    assert "run-cad" in world.kube.pods
