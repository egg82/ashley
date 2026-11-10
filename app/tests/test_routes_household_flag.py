"""`routes.parse` and the `"household": true` flag: which text tasks a household may choose for is an explicit field in
the routes data, never on `action_judge`, never on a task that is not a text task; and an operator's plain list turns
it off for that task."""

from typing import Any

import pytest
from ashley.inference import routes
from household_routes_support import data, raw


def test_the_flag_names_the_household_tasks_and_like_follows_a_flagged_list() -> None:
    parsed = routes.parse(data(), {})
    assert parsed.households == {"command", "chat", "brainstorm"}
    assert parsed.by_task["escalated"] == parsed.by_task["brainstorm"]
    assert "escalated" not in parsed.households


def test_the_flag_and_fallback_together() -> None:
    source = data()
    source["tasks"]["chat"]["fallback"] = False
    parsed = routes.parse(source, {})
    assert "chat" in parsed.households and "chat" in parsed.waits_for_first


@pytest.mark.parametrize("entry", [
    {"household": False, "routes": [raw("alpha", "m1")]},
    {"household": "yes", "routes": [raw("alpha", "m1")]},
    {"household": True, "fallback": True, "routes": [raw("alpha", "m1")]},
    {"household": True, "other": 1, "routes": [raw("alpha", "m1")]},
    {"routes": [raw("alpha", "m1")]},
])
def test_a_malformed_wrapper_is_refused(entry: dict[str, Any]) -> None:
    source = data()
    source["tasks"]["chat"] = entry
    with pytest.raises(ValueError, match="chat"):
        routes.parse(source, {})


def test_action_judge_is_never_a_households() -> None:
    source = data()
    source["tasks"]["action_judge"] = {"household": True, "routes": [raw("alpha", "m1")]}
    with pytest.raises(ValueError, match="action_judge"):
        routes.parse(source, {})
    assert routes.NEVER_HOUSEHOLD == {"action_judge"}
    assert "action_judge" not in routes.load({}).households


def test_only_a_text_task_may_be_a_households() -> None:
    source = data()
    source["tasks"]["embed"] = {"household": True, "routes": [raw("fastembed", "x")]}
    with pytest.raises(ValueError, match="embed"):
        routes.parse(source, {})


def test_an_operators_plain_list_turns_the_flag_off_for_that_task() -> None:
    overlaid = routes.overlay(data(), {"tasks": {"chat": [raw("beta", "m1")]}})
    assert routes.parse(overlaid, {}).households == {"command", "brainstorm"}


def test_deployment_is_the_shipped_data_with_the_operators_file_over_it(tmp_path: Any) -> None:
    path = tmp_path / "routes.json"
    path.write_text('{"tasks": {"chat": [{"provider": "local", "model": "q", "timeout_s": 5}]}}')
    got: dict[str, Any] = routes.deployment(str(path))
    assert got["tasks"]["chat"] == [{"provider": "local", "model": "q", "timeout_s": 5}]
    assert routes.parse(got, {}).by_task["command"] == routes.load({}).by_task["command"]
    with pytest.raises(ValueError, match="ROUTES_FILE"):
        routes.deployment(str(tmp_path / "missing.json"))
