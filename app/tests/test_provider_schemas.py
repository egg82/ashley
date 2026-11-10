"""No tool schema or response format the app can send a chat provider carries a keyword that provider rejects.

Gemini answered every chat call 400 for two hours when one tool's schema had nested `maxItems`, and the router's fall
back to another model hid it. The schemas are collected through the real tool sources and wire modules, so a tool added
tomorrow is checked; the rejected keywords are data (`provider_schema_rejects.json`), each with its source."""

import json
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import pytest
from ashley.inference.model import ToolSpec
from ashley.inference.routes import TASKS
from provider_schema_support import RULES, SHAPES, WIRES, Sent, collect, offered, rules, unlisted_formats, used_formats, violations
from source_tree import Parsed
from ashley.tools import reminder_conditions


pytestmark = pytest.mark.usefixtures("sure_ledger_wired")

PROVIDERS = sorted(WIRES)
FLOOR = 40
FORMAT_FLOOR = 6



@pytest.mark.parametrize("provider", PROVIDERS)
def test_nothing_sent_to_a_provider_carries_a_keyword_it_rejects(provider: str) -> None:
    sent = collect(provider)
    assert len(sent) >= FLOOR
    assert violations(provider, sent) == []


def test_the_collection_reaches_every_source_a_turn_can_offer() -> None:
    names = {s.name for s in offered()}
    assert len(names) >= FLOOR
    assert {"remind", "remind_on_money", "arm_reminder", "change_reminder", "bench_read", "bench_run", "open_bench",
            "look_up", "household_devices", "house_automations", "bench_propose_install", "skill_read", "move_page",
            "git_projects", "money_accounts", "run_code", "watch", "unwatch", "watches"} <= names


def test_every_provider_a_text_task_routes_to_is_gated() -> None:
    data = json.loads((RULES.parent.parent / "ashley" / "inference" / "routes.json").read_text())
    routed = {e["provider"] for task in TASKS for e in data["tasks"].get(task, [])
              if isinstance(data["tasks"].get(task), list)}
    assert routed <= set(WIRES)
    assert set(rules()) == set(WIRES)


def test_every_response_format_the_app_asks_for_is_collected(python_tree: Mapping[Path, Parsed]) -> None:
    assert len(used_formats(python_tree)) >= FORMAT_FLOOR
    assert unlisted_formats(python_tree) == set()


def test_every_rule_names_a_known_shape_and_a_source() -> None:
    for provider, entries in rules().items():
        for entry in entries:
            assert entry["shape"] in SHAPES and entry["keyword"], provider
            assert entry["source"].startswith("recorded 400") or "https://" in entry["source"], entry


def _old_conditions() -> ToolSpec:
    schema = deepcopy(dict(reminder_conditions.schema()))
    schema["maxItems"] = 3
    inner = schema["items"]
    assert isinstance(inner, dict)
    inner["maxItems"] = 6
    return ToolSpec("remind_on_money_old", "x", {"type": "object", "properties": {"conditions": schema}})


def test_the_gate_goes_red_on_the_schema_that_took_gemini_down() -> None:
    planted = collect("gemini", [*offered(), _old_conditions()])
    assert violations("gemini", planted) == [
        "tool remind_on_money_old: maxItems (array_and_its_array_items)"]
    assert violations("anthropic", collect("anthropic", [*offered(), _old_conditions()])) == []


def test_each_shape_fires_on_its_own_case_and_stays_quiet_on_a_near_miss() -> None:
    both = {"type": "array", "maxItems": 2, "items": {"type": "array", "maxItems": 2, "items": {"type": "string"}}}
    outer_only = {"type": "array", "maxItems": 2, "items": {"type": "array", "items": {"type": "string"}}}
    strings = {"type": "array", "maxItems": 2, "items": {"type": "string"}}
    wrapped = {"type": "object", "properties": {"maxItems": {"type": "integer"}, "list": both}}
    assert SHAPES["array_and_its_array_items"](both, "maxItems")
    assert not SHAPES["array_and_its_array_items"](outer_only, "maxItems")
    assert not SHAPES["array_and_its_array_items"](strings, "maxItems")
    assert violations("gemini", [Sent("a", wrapped)]) == ["a: maxItems (array_and_its_array_items)"]
    assert violations("gemini", [Sent("b", {"type": "object", "properties": {"maxItems": {"type": "integer"}}})]) == []
