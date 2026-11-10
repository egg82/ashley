"""Language profiles in the sandbox's tunables: Python is the top-level fields, every other language a `Profile` that
is run only once it is given a pinned image."""

import copy
from typing import Any

import pytest
from ashley.runs.config import RunsConfig, load, parse
from sandbox_languages_support import CAD, config, shipped_data


def test_the_shipped_tunables_hold_a_build123d_profile_with_no_image() -> None:
    shipped = load()
    profile = shipped.languages["build123d"]
    assert (profile.script_timeout_s, profile.pod_deadline_s) == (60, 120)
    assert (profile.cpu, profile.cpu_request, profile.memory, profile.work_mib) == ("1", "500m", "1Gi", 32)
    assert profile.image == ""


def test_python_is_a_profile_under_languages_with_its_image() -> None:
    shipped = load()
    profile = shipped.profile("python")
    assert profile is not None and profile is shipped.languages["python"]
    assert "@sha256:" in profile.image
    assert (profile.script_timeout_s, profile.pod_deadline_s) == (10, 30)
    assert (profile.cpu, profile.cpu_request, profile.memory) == ("500m", "250m", "256Mi")
    assert (profile.work_mib, profile.log_bytes) == (32, 262144)


def test_a_language_with_no_image_is_not_offered() -> None:
    shipped = load()
    assert shipped.offered() == ("python",)
    assert shipped.profile("build123d") is None


def test_giving_build123d_an_image_offers_it_after_python() -> None:
    given = load().with_image("build123d", CAD)
    assert given.offered() == ("python", "build123d")
    profile = given.profile("build123d")
    assert profile is not None and profile.image == CAD
    assert (profile.script_timeout_s, profile.pod_deadline_s, profile.memory) == (60, 120, "1Gi")


def test_giving_an_image_changes_a_copy_and_not_the_python_profile() -> None:
    before = load()
    given = before.with_image("build123d", CAD)
    assert before.offered() == ("python",) and before.languages["build123d"].image == ""
    python = given.profile("python")
    assert python is not None and python.image == before.languages["python"].image


@pytest.mark.parametrize("image", [
    "docker.io/library/python:3.13", "registry.test/ashley-cad:latest", "ashley-cad@sha256:short", "", "@sha256:" + "a" * 64])
def test_an_image_not_pinned_by_digest_is_refused(image: str) -> None:
    with pytest.raises(ValueError):
        load().with_image("build123d", image)


def test_an_image_for_a_language_with_no_profile_is_refused() -> None:
    with pytest.raises(ValueError):
        load().with_image("cobol", CAD)


def test_the_longest_deadline_counts_a_profile_that_is_not_run() -> None:
    assert load().longest_deadline_s() == 120
    assert config().longest_deadline_s() == 120


def test_the_longest_deadline_is_python_s_when_it_is_the_longest() -> None:
    data = shipped_data()
    data["languages"]["python"]["pod_deadline_s"] = 200
    assert parse(data).longest_deadline_s() == 200


def test_languages_without_python_are_a_value_error() -> None:
    data = shipped_data()
    del data["languages"]["python"]
    with pytest.raises(ValueError):
        parse(data)


def test_the_shipped_tunables_parse_to_what_load_gives() -> None:
    assert parse(shipped_data()) == load()
    assert isinstance(load(), RunsConfig)


def test_a_distinct_profile_keeps_each_field_it_was_given() -> None:
    profile = config().profile("build123d")
    assert profile is not None
    assert (profile.work_mib, profile.log_bytes) == (16, 300_000)


def bad(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(shipped_data())
    data["languages"]["build123d"].update(changes)
    return data


@pytest.mark.parametrize("changes", [
    {"pod_deadline_s": 60}, {"pod_deadline_s": 30}, {"script_timeout_s": 0}, {"script_timeout_s": -1},
    {"pod_deadline_s": 0}, {"work_mib": 0}, {"log_bytes": 0}, {"log_bytes": 100}, {"cpu": ""}, {"memory": ""},
    {"memory": 1024}, {"script_timeout_s": "60"}, {"unknown_key": 1},
])
def test_a_bad_profile_is_a_value_error(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        parse(bad(**changes))


@pytest.mark.parametrize("key", ["script_timeout_s", "pod_deadline_s", "cpu", "cpu_request", "memory", "work_mib", "log_bytes"])
def test_a_profile_missing_a_field_is_a_value_error(key: str) -> None:
    data = shipped_data()
    del data["languages"]["build123d"][key]
    with pytest.raises(ValueError):
        parse(data)


@pytest.mark.parametrize("languages", ["x", 3, ["build123d"], {"build123d": 3}, {"build123d": []}])
def test_languages_that_are_not_profiles_are_a_value_error(languages: object) -> None:
    data = shipped_data()
    data["languages"] = languages
    with pytest.raises(ValueError):
        parse(data)


def test_a_python_entry_under_languages_is_refused() -> None:
    data = shipped_data()
    data["languages"]["python"] = copy.deepcopy(data["languages"]["build123d"])
    with pytest.raises(ValueError):
        parse(data)


def test_a_profile_whose_deadline_just_leaves_room_for_its_timeout_parses() -> None:
    assert parse(bad(pod_deadline_s=61)).languages["build123d"].pod_deadline_s == 61

