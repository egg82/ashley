"""The tiers as data (`tiers.json`) and what reads them: the shipped file loads and holds the owner-approved tier b and c
lists, the first rule that matches a house target decides, the household's consequential entities and a target of another
domain are always judged, an argument rule only escalates, and `HouseTools.tier` resolves what a `house_do` names."""

import asyncio
import json
from pathlib import Path

import pytest
from ashley.inference.model import ToolCall
from ashley.tools import house_tier, tiers_config
from ashley.tools.house_act import DO, ASK
from ashley.tools.house_look_config import load as look_config
from ashley.tools.house_state_config import load as state_config
from ashley.tools.house_tools import HouseTools
from ashley.tools.house_act import Rules
from ashley.tools.home_assistant_config import load as ha_config
from ashley.home_assistant.irreversible import load as irreversible
from ashley.tools.tiers import Target, by_arguments, of_house_do
from house_double_support import MemoryHouse, state

CONFIG = tiers_config.load()
ALANA_HOUSEHOLD = 1


def target(entity: str, device_class: str | None = None) -> Target:
    return Target(entity, entity.split(".")[0], device_class)


@pytest.mark.parametrize("action", ["light.turn_on", "fan.turn_off", "media_player.volume_set", "media_player.media_pause",
                                    "scene.turn_on", "climate.set_temperature", "climate.set_hvac_mode",
                                    "input_boolean.turn_on", "input_number.set_value", "input_select.select_option",
                                    "input_button.press", "timer.start", "vacuum.start", "vacuum.return_to_base",
                                    "todo.add_item", "todo.update_item", "cover.open_cover", "switch.turn_on"])
def test_the_approved_low_stakes_actions_run(action: str) -> None:
    assert of_house_do(action, (target(f"{action.split('.')[0]}.x"),)) == "runs"


@pytest.mark.parametrize("action", ["lock.unlock", "alarm_control_panel.alarm_disarm", "siren.turn_on", "camera.turn_off",
                                    "automation.turn_off", "automation.trigger", "script.turn_on", "button.press",
                                    "notify.mobile_app", "homeassistant.turn_off", "todo.remove_item", "vacuum.clean_spot",
                                    "climate.turn_off", "scene.create", "never.heard_of_it"])
def test_every_other_action_is_judged(action: str) -> None:
    assert of_house_do(action, (target(f"{action.split('.')[0]}.x"),)) == "judged"


@pytest.mark.parametrize("device_class", ["garage", "gate", "door"])
def test_a_garage_gate_or_door_cover_is_judged_and_another_cover_runs(device_class: str) -> None:
    assert of_house_do("cover.open_cover", (target("cover.g", device_class),)) == "judged"
    assert of_house_do("cover.open_cover", (target("cover.blind", "blind"), target("cover.shade"))) == "runs"


def test_an_outlet_switch_is_judged_and_a_lamp_switch_runs() -> None:
    assert of_house_do("switch.turn_on", (target("switch.plug", "outlet"),)) == "judged"
    assert of_house_do("switch.turn_on", (target("switch.lamp", "switch"),)) == "runs"


def test_one_judged_target_among_several_judges_the_call() -> None:
    assert of_house_do("switch.turn_on", (target("switch.lamp"), target("switch.plug", "outlet"))) == "judged"


def test_a_household_s_consequential_entity_is_judged_whatever_a_rule_says() -> None:
    listed = ("switch.garage_relay",)
    assert of_house_do("switch.turn_on", (target("switch.garage_relay"),), consequential=listed) == "judged"
    assert of_house_do("switch.turn_on", (target("switch.garage_relay"),)) == "runs", "unlisted"
    assert of_house_do("switch.turn_on", (target("switch.lamp"),), consequential=listed) == "runs"


def test_a_target_of_another_domain_than_the_action_is_judged() -> None:
    assert of_house_do("light.turn_off", (target("lock.front_door"),)) == "judged"


def test_a_call_naming_no_target_is_judged_as_its_action_alone() -> None:
    assert of_house_do("light.turn_off", ()) == "runs" and of_house_do("lock.lock", ()) == "judged"


def call(tool: str, **arguments: object) -> ToolCall:
    return ToolCall("c", tool, arguments)


@pytest.mark.parametrize(("tool", "arguments", "tier"), [
    ("mail_label", {"folder": "archive"}, "judged"), ("mail_label", {"folder": " Trash "}, "judged"),
    ("mail_label", {"folder": "spam", "add": ["x"]}, "judged"), ("mail_label", {"folder": "inbox"}, None),
    ("mail_label", {"add": ["x"]}, None), ("mail_label", {"unread": False}, None),
    ("remind", {"tools": ["mail_label"]}, "judged"), ("remind", {"tools": []}, None), ("remind", {"at": "2026-11-09"}, None),
    ("watch", {"tools": ["mail_label"]}, "judged"), ("watch", {"kind": "mail_inbox"}, None),
    ("mail_send", {"folder": "trash"}, None)])
def test_an_argument_rule_escalates_only_the_call_it_names(tool: str, arguments: dict[str, object], tier: str | None) -> None:
    assert by_arguments(call(tool, **arguments)) == tier


def test_the_shipped_file_names_exactly_the_documented_keys_and_ships_no_household_entity_list() -> None:
    raw = json.loads(Path(tiers_config.FILE).read_text())
    assert set(raw) == {"default", "arguments", "house_do"} and raw["default"] == "judged"
    assert len(CONFIG.house_do) > 10


@pytest.mark.parametrize("bad", [
    {"default": "maybe", "arguments": [], "house_do": []},
    {"default": "judged", "arguments": [], "house_do": [{"tier": "runs"}]},
    {"default": "judged", "arguments": [], "house_do": [{"tier": "runs", "domain": "a", "action": "a.b"}]},
    {"default": "judged", "arguments": [{"tool": "x", "argument": "", "tier": "judged"}], "house_do": []},
    {"default": "judged", "arguments": [], "house_do": [], "consequential_entities": {}},
    {"default": "judged", "arguments": []}, [], "x"])
def test_a_malformed_file_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        tiers_config.parse(bad)


def tools_over(house: MemoryHouse, household_id: int = ALANA_HOUSEHOLD) -> HouseTools:
    ha = ha_config()
    return HouseTools(house, Rules(ha.excluded, (), irreversible()), look_config(), state_config(), "", household_id)


def tier_of(tools: HouseTools, tool: str, **arguments: object) -> str | None:
    return asyncio.run(tools.tier(call(tool, **arguments)))


def test_the_house_source_resolves_what_house_do_names_and_judges_by_what_it_is() -> None:
    house = MemoryHouse([state("light.porch", "Porch light", "off"), state("switch.lamp", "Desk lamp", "off"),
                         state("switch.relay", "Garage relay", "off", device_class="outlet"),
                         state("cover.garage", "Garage door", "closed", device_class="garage"),
                         state("lock.front", "Front door", "locked")])
    tools = tools_over(house)
    assert tier_of(tools, DO, action="light.turn_on", name="porch light") == "runs"
    assert tier_of(tools, DO, action="switch.turn_on", ids=["switch.lamp"]) == "runs"
    assert tier_of(tools, DO, action="switch.turn_on", ids=["switch.relay"]) == "judged"
    assert tier_of(tools, DO, action="cover.open_cover", ids=["cover.garage"]) == "judged"
    assert tier_of(tools, DO, action="lock.unlock", ids=["lock.front"]) == "judged"
    assert tier_of(tools, DO, action="light.turn_on", ids=["lock.front"]) == "judged"
    assert house.done == [], "asking the tier changes nothing"


def test_the_house_source_judges_a_call_it_cannot_read_or_while_the_house_is_down() -> None:
    house = MemoryHouse([state("light.porch", "Porch light", "off")])
    tools = tools_over(house)
    assert tier_of(tools, DO, name="porch light") == "judged", "no action"
    assert tier_of(tools, DO, action="light.turn_on", ids="porch") == "judged", "ids is not a list"
    house.down = True
    assert tier_of(tools, DO, action="light.turn_on", name="porch light") == "judged"


def test_the_house_source_leaves_another_tool_to_the_argument_rules() -> None:
    tools = tools_over(MemoryHouse([]))
    assert tier_of(tools, ASK, action="calendar.get_events") is None
    assert tier_of(tools, "mail_label", folder="trash") == "judged"


def test_a_household_s_listed_entity_is_judged_through_the_house_source() -> None:
    house = MemoryHouse([state("switch.lamp", "Desk lamp", "off")])
    ask = {"action": "switch.turn_on", "ids": ["switch.lamp"]}
    assert asyncio.run(house_tier.of_call(house, ask, CONFIG, ("switch.lamp",))) == "judged"
    assert asyncio.run(house_tier.of_call(house, ask, CONFIG)) == "runs"
