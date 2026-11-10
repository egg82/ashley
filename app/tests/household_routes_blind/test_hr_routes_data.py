"""Pins the routes-data side of the contract (`routes`): the `"household": true` field of a task entry, `action_judge`
never being one however the data says, and `routes.deployment` as the shipped data with the operator's file over it."""

import json
from pathlib import Path
from typing import Any

import pytest
from ashley.inference import routes
from household_routes_blind_support import deployment_data, route, stubs

PROVIDERS = dict(stubs())
TWO = [route("a", "m1"), route("b", "m2")]


def parsed(**tasks: object) -> routes.Routes:
    return routes.parse(deployment_data(**{"escalated": TWO, **tasks}), PROVIDERS)


def test_a_task_entry_flagged_household_is_a_households_task() -> None:
    assert parsed().households == {"chat", "brainstorm", "wrap_up"}


def test_no_flag_means_no_household_task() -> None:
    plain = {t: TWO for t in routes.TASKS}
    assert routes.parse({"cooldown_s": 60, "tasks": plain}, PROVIDERS).households == frozenset()


def test_a_household_task_lists_its_routes_like_any_other() -> None:
    assert [(r.provider, r.model) for r in parsed().by_task["chat"]] == [("a", "m1"), ("b", "m2")]


def test_the_flag_and_fallback_may_be_given_together() -> None:
    loaded = parsed(chat={"household": True, "fallback": False, "routes": TWO})
    assert "chat" in loaded.households and "chat" in loaded.waits_for_first


@pytest.mark.parametrize("flag", ["yes", 1, None, "true"])
def test_only_a_boolean_flag_is_accepted(flag: object) -> None:
    with pytest.raises(ValueError, match="chat"):
        parsed(chat={"household": flag, "routes": TWO})


def test_a_household_flag_on_action_judge_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="action_judge"):
        parsed(action_judge={"household": True, "routes": TWO})


def test_action_judge_is_never_a_household_task_by_the_rule_itself() -> None:
    assert "action_judge" in routes.NEVER_HOUSEHOLD and routes.NEVER_HOUSEHOLD <= set(routes.TASKS)
    assert "action_judge" not in routes.load({}).households


def test_a_speech_task_cannot_be_a_households() -> None:
    data = deployment_data()
    data["tasks"]["speak"] = {"household": True, "routes": TWO}
    with pytest.raises(ValueError, match="speak"):
        routes.parse(data, PROVIDERS)


def test_a_flag_riding_in_the_operators_file_for_action_judge_is_refused_naming_the_file(tmp_path: Path) -> None:
    f = tmp_path / "routes.json"
    f.write_text(json.dumps({"tasks": {"action_judge": {"household": True, "routes": TWO}}}))
    with pytest.raises(ValueError, match="ROUTES_FILE"):
        routes.load({}, str(f))


def test_deployment_without_a_file_is_the_shipped_data_and_parses_to_what_load_gives() -> None:
    data = routes.deployment()
    assert set(data) == {"cooldown_s", "tasks"}
    assert routes.parse(data, {}) == routes.load({})


def test_deployment_lays_the_operators_file_over_the_shipped_data(tmp_path: Path) -> None:
    f = tmp_path / "routes.json"
    f.write_text(json.dumps({"cooldown_s": 7, "tasks": {"chat": {"household": True, "routes": TWO}}}))
    shipped: dict[str, Any] = routes.deployment()
    over: dict[str, Any] = routes.deployment(str(f))
    assert over["cooldown_s"] == 7
    assert over["tasks"]["chat"] == {"household": True, "routes": TWO}
    others: dict[str, Any] = {t: e for t, e in shipped["tasks"].items() if t != "chat"}
    assert {t: e for t, e in over["tasks"].items() if t != "chat"} == others
    assert routes.parse(over, {}) == routes.load({}, str(f))


def test_deployment_is_what_the_operator_overlay_makes_of_the_shipped_data(tmp_path: Path) -> None:
    f = tmp_path / "routes.json"
    operator = {"tasks": {"command": TWO}}
    f.write_text(json.dumps(operator))
    assert routes.deployment(str(f)) == routes.overlay(routes.deployment(), operator)


@pytest.mark.parametrize("text", ["{", "[]", '{"nope": 1}'])
def test_deployment_raises_value_error_naming_routes_file_for_a_file_it_cannot_overlay(tmp_path: Path, text: str) -> None:
    f = tmp_path / "routes.json"
    f.write_text(text)
    with pytest.raises(ValueError, match="ROUTES_FILE"):
        routes.deployment(str(f))


def test_deployment_raises_value_error_naming_routes_file_for_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ROUTES_FILE"):
        routes.deployment(str(tmp_path / "absent.json"))


def test_deployment_does_not_change_the_shipped_data_between_calls(tmp_path: Path) -> None:
    f = tmp_path / "routes.json"
    f.write_text(json.dumps({"tasks": {"command": TWO}}))
    before = routes.deployment()
    routes.deployment(str(f))
    assert routes.deployment() == before
