"""The pod a job runs in, per language: the profile's image, deadline, limits and work directory, the code run's
isolation unchanged, and a language with no image never run in another's."""

from typing import Any

import pytest
from ashley.runs.model import Job, Language
from ashley.runs.pod_spec import manifest
from sandbox_languages_support import CAD, check_isolated, config, container, decoded_values, job, python_only, without_profile

RUNNER = "print('runner')"


@pytest.mark.parametrize("language", ["python", "build123d"])
def test_each_language_s_pod_is_isolated_and_made_from_its_profile(language: Language) -> None:
    cfg = config()
    check_isolated(manifest(job(language), cfg, RUNNER), cfg, language)


def test_a_build123d_pod_runs_the_cad_image_with_its_own_deadline_and_limits() -> None:
    made = manifest(job("build123d"), config(), RUNNER)
    assert container(made)["image"] == CAD
    assert made["spec"]["activeDeadlineSeconds"] == 120
    assert container(made)["resources"]["limits"] == {"cpu": "1", "memory": "1Gi"}
    assert container(made)["resources"]["requests"] == {"cpu": "500m", "memory": "1Gi"}


def test_a_python_pod_keeps_the_python_image_and_limits_when_build123d_is_offered() -> None:
    cfg = config()
    made = manifest(job("python"), cfg, RUNNER)
    assert container(made)["image"] == cfg.languages["python"].image != CAD
    assert made["spec"]["activeDeadlineSeconds"] == 30
    assert container(made)["resources"]["limits"] == {"cpu": "500m", "memory": "256Mi"}


def test_the_two_languages_pods_differ_only_in_what_the_profile_sets() -> None:
    cfg = config()
    python = manifest(job("python", "run-9", "print(1)"), cfg, RUNNER)
    cad = manifest(job("build123d", "run-9", "print(1)"), cfg, RUNNER)
    assert without_profile(python) == without_profile(cad)


def test_the_script_reaches_a_build123d_pod_through_its_environment_only() -> None:
    made = manifest(job("build123d", script="from ashley_cad import show"), config(), RUNNER)
    assert "from ashley_cad import show" in decoded_values(made)
    assert "from ashley_cad import show" not in str(container(made).get("command", "")) + str(container(made).get("args", ""))


def test_a_language_with_no_image_has_no_pod() -> None:
    with pytest.raises(ValueError):
        manifest(job("build123d"), python_only(), RUNNER)


def test_a_python_pod_still_has_a_pod_when_build123d_has_no_image() -> None:
    cfg = python_only()
    assert container(manifest(job("python"), cfg, RUNNER))["image"] == cfg.languages["python"].image


def test_a_language_the_config_has_no_profile_for_has_no_pod() -> None:
    fields: dict[str, Any] = {"name": "run-1", "language": "cobol", "script": "x", "stdin": "", "files": {}}
    unknown = Job(**fields)
    with pytest.raises(ValueError):
        manifest(unknown, config(), RUNNER)
