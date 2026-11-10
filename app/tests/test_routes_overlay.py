"""`ROUTES_FILE`: an operator's overlay of the shipped routes, merged by `routes.overlay` and read by `routes.load`."""

import json
from pathlib import Path
from typing import Any

import pytest
from ashley import settings
from ashley.inference import routes

SHIPPED: dict[str, Any] = json.loads(Path(routes.__file__).with_name("routes.json").read_text())
LOCAL = [{"provider": "local", "model": "qwen", "timeout_s": 20}]


def test_a_task_in_the_overlay_replaces_its_whole_list_and_the_rest_are_kept() -> None:
    merged: dict[str, Any] = routes.overlay(SHIPPED, {"tasks": {"chat": LOCAL}})
    assert merged["tasks"]["chat"] == LOCAL
    assert {t: v for t, v in merged["tasks"].items() if t != "chat"} == {
        t: v for t, v in SHIPPED["tasks"].items() if t != "chat"}


def test_an_absent_cooldown_is_kept_and_a_given_one_replaces() -> None:
    assert routes.overlay(SHIPPED, {"tasks": {}})["cooldown_s"] == SHIPPED["cooldown_s"]
    assert routes.overlay(SHIPPED, {"cooldown_s": 5})["cooldown_s"] == 5


def test_overlay_leaves_both_inputs_untouched() -> None:
    before = json.dumps(SHIPPED)
    routes.overlay(SHIPPED, {"cooldown_s": 5, "tasks": {"chat": LOCAL}})
    assert json.dumps(SHIPPED) == before


def test_an_overlay_that_changes_nothing_parses_to_the_shipped_routes() -> None:
    assert routes.parse(routes.overlay(SHIPPED, {}), {}) == routes.load({})


def test_an_overlaid_task_that_is_not_a_task_is_rejected_by_parse() -> None:
    with pytest.raises(ValueError, match="unknown.*chatt"):
        routes.parse(routes.overlay(SHIPPED, {"tasks": {"chatt": LOCAL}}), {})


def test_the_overlay_replacing_a_waiting_task_with_a_plain_list_drops_the_wait() -> None:
    merged = routes.parse(routes.overlay(SHIPPED, {"tasks": {"memory_write": LOCAL}}), {})
    assert merged.waits_for_first == frozenset() and merged.by_task["memory_write"][0].provider == "local"


def test_a_task_that_likens_another_follows_the_overlaid_list() -> None:
    merged = routes.parse(routes.overlay(SHIPPED, {"tasks": {"brainstorm": LOCAL}}), {})
    assert merged.by_task["escalated"] == merged.by_task["brainstorm"]
    assert merged.by_task["escalated"][0].provider == "local"


@pytest.mark.parametrize("operator", [[], {"tasks": []}, {"cooldown": 5}, {"tasks": {}, "extra": 1}])
def test_an_overlay_of_the_wrong_shape_is_a_value_error(operator: object) -> None:
    with pytest.raises(ValueError, match="overlay"):
        routes.overlay(SHIPPED, operator)


def write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "routes.json"
    path.write_text(text)
    return str(path)


def test_load_applies_the_file_over_the_shipped_routes(tmp_path: Path) -> None:
    loaded = routes.load({}, write(tmp_path, json.dumps({"tasks": {"chat": LOCAL}})))
    assert loaded.by_task["chat"][0].model == "qwen"
    assert loaded.by_task["command"] == routes.load({}).by_task["command"]


def test_load_without_a_path_is_the_shipped_routes() -> None:
    assert routes.load({}, "") == routes.load({})


@pytest.mark.parametrize("text", ["{not json", "[]", '{"tasks": {"nope": []}}', '{"tasks": {"chat": []}}'])
def test_a_bad_file_fails_naming_routes_file(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError, match="ROUTES_FILE"):
        routes.load({}, write(tmp_path, text))


def test_a_missing_file_fails_naming_routes_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ROUTES_FILE"):
        routes.load({}, str(tmp_path / "absent.json"))


def test_settings_read_routes_file_and_default_to_none() -> None:
    base = {"DATABASE_URL": "postgresql://x"}
    assert settings.from_env(base).routes_file == ""
    assert settings.from_env({**base, "ROUTES_FILE": "/etc/ashley/routes.json"}).routes_file == "/etc/ashley/routes.json"
