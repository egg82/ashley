"""The sandbox's tunables and the Kubernetes API client."""

from pathlib import Path
from typing import Any

import pytest
from ashley.runs.config import Profile, RunsConfig, load, parse
from ashley.runs.kube_api import KubeError
from rcb_support import run
from sandbox_support import FakeKube, PYTHON

PROFILE: dict[str, Any] = {
    "image": PYTHON.image, "script_timeout_s": 10, "pod_deadline_s": 30, "cpu": "500m", "cpu_request": "250m",
    "memory": "256Mi", "work_mib": 32, "log_bytes": 4096}
GOOD: dict[str, Any] = {
    "namespace": "ashley-sandbox", "runtime_class": "gvisor", "max_script_chars": 100, "max_stdin_chars": 100,
    "output_chars": 50, "file_chars": 40, "max_files": 2, "poll_s": 0.5, "languages": {"python": PROFILE}}


def python(**change: Any) -> dict[str, Any]:
    return {**GOOD, "languages": {"python": {**PROFILE, **change}}}


def test_the_shipped_tunables_load_pinned_and_in_the_sandbox_namespace() -> None:
    shipped = load()
    assert shipped.namespace == "ashley-sandbox" and shipped.runtime_class == "gvisor"
    python = shipped.languages["python"]
    assert "@sha256:" in python.image and python.pod_deadline_s > python.script_timeout_s


def test_a_complete_config_parses() -> None:
    expected: dict[str, Any] = {**GOOD, "languages": {"python": Profile(**PROFILE)}}
    assert parse(GOOD) == RunsConfig(**expected)


@pytest.mark.parametrize("change", [
    {"image": "docker.io/library/python:3.13"}, {"pod_deadline_s": 10}, {"pod_deadline_s": 5}, {"script_timeout_s": 0},
    {"work_mib": -1}])
def test_a_bad_python_profile_is_a_value_error(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse(python(**change))


@pytest.mark.parametrize("change", [{"max_files": 0}, {"poll_s": 0}, {"output_chars": "50"}, {"unknown_key": 1}])
def test_a_bad_config_is_a_value_error(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse({**GOOD, **change})


def test_an_image_pinned_by_a_malformed_digest_is_refused() -> None:
    with pytest.raises(ValueError):
        parse(python(image="python@sha256:short"))


@pytest.mark.parametrize("key", sorted(GOOD))
def test_a_missing_key_is_a_value_error(key: str) -> None:
    with pytest.raises(ValueError):
        parse({k: v for k, v in GOOD.items() if k != key})


@pytest.mark.parametrize("key", sorted(PROFILE))
def test_a_missing_python_profile_key_is_a_value_error(key: str) -> None:
    with pytest.raises(ValueError):
        parse({**GOOD, "languages": {"python": {k: v for k, v in PROFILE.items() if k != key}}})


@pytest.mark.parametrize("data", [None, [], "x", 3])
def test_a_config_that_is_not_an_object_is_a_value_error(data: object) -> None:
    with pytest.raises(ValueError):
        parse(data)


def test_the_error_names_the_status_and_never_the_response_body(tmp_path: Path) -> None:
    kube = FakeKube(tmp_path / "t")
    kube.fail = lambda request: 403
    with pytest.raises(KubeError) as raised:
        run(kube.api().create_pod("ashley-sandbox", {"metadata": {"name": "run-1"}}))
    assert "403" in str(raised.value) and "message" not in str(raised.value)


def test_a_pod_that_is_not_there_is_none_and_deleting_it_is_false(tmp_path: Path) -> None:
    api = FakeKube(tmp_path / "t").api()
    assert run(api.pod("ashley-sandbox", "run-404")) is None
    assert run(api.delete_pod("ashley-sandbox", "run-404")) is False


def test_a_created_pod_can_be_read_and_deleted_once(tmp_path: Path) -> None:
    kube = FakeKube(tmp_path / "t")
    api = kube.api()
    run(api.create_pod("ashley-sandbox", {"metadata": {"name": "run-1"}, "spec": {}}))
    found = run(api.pod("ashley-sandbox", "run-1"))
    assert found is not None and found["metadata"]["name"] == "run-1"
    assert run(api.delete_pod("ashley-sandbox", "run-1")) is True
    assert run(api.delete_pod("ashley-sandbox", "run-1")) is False


def test_the_bearer_token_is_the_file_s_current_content_on_every_call(tmp_path: Path) -> None:
    kube = FakeKube(tmp_path / "t")
    api = kube.api()
    run(api.pod("ashley-sandbox", "a"))
    (tmp_path / "t").write_text("second")
    run(api.pod("ashley-sandbox", "a"))
    assert kube.tokens == ["Bearer token-one", "Bearer second"]
