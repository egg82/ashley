"""A fake house with one entity of every kind the tier examples name, and the real `HouseTools` over it. The one guess
about the tiers config (G3 in `taint_tiers_blind_support`) is in `house_tools`."""

import json
from collections.abc import Mapping

from ashley.home_assistant.house import ActionInfo
from ashley.inference.model import ToolCall
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_tools import HouseTools
from house_double_support import MemoryHouse, state
from house_settings_support import house_rules

HOUSEHOLD = 1  # the id a fresh test database gives the first household; `opened` asserts it
CATALOGUE = {
    "light.turn_on": {}, "todo.add_item": {"item": "what"}, "todo.update_item": {"item": "which"},
    "cover.open_cover": {}, "media_player.volume_set": {}, "climate.set_temperature": {}, "timer.start": {},
    "scene.turn_on": {}, "input_boolean.turn_on": {}, "switch.turn_on": {}, "lock.unlock": {}, "lock.lock": {},
    "script.turn_on": {}, "alarm_control_panel.alarm_disarm": {}, "mystery.do_it": {}, "notify.send_message": {},
    "automation.trigger": {}, "siren.turn_on": {}, "button.press": {}, "homeassistant.turn_off": {},
    "todo.get_items": {}, "fan.turn_on": {}, "vacuum.start": {},
}


def the_house() -> MemoryHouse:
    things = [state("light.porch", "Porch", "off"), state("light.den", "Den", "off"),
              state("todo.inbox", "Inbox", "1"), state("cover.blinds", "Blinds", "closed", device_class="blind"),
              state("cover.garage", "Garage door", "closed", device_class="garage"),
              state("media_player.tv", "TV", "off"), state("climate.den", "Den", "idle"), state("timer.tea", "Tea", "idle"),
              state("scene.movie", "Movie", "scening"), state("input_boolean.guest", "Guest", "off"),
              state("switch.lamp", "Lamp", "off", device_class="switch"),
              state("switch.garage_relay", "Garage relay", "off", device_class="switch"),
              state("switch.plug", "Plug", "off", device_class="outlet"),
              state("lock.front", "Front door", "locked"), state("script.goodnight", "Goodnight", "off"),
              state("alarm_control_panel.home", "Alarm", "armed_home"), state("mystery.thing", "Thing", "on"),
              state("notify.phone", "Phone", "unknown"), state("automation.arrive", "Arrive", "on"),
              state("siren.hall", "Siren", "off"), state("button.bell", "Bell", "unknown"),
              state("homeassistant.x", "X", "on"), state("fan.den", "Fan", "off"), state("vacuum.robot", "Robot", "docked")]
    house = MemoryHouse(things=things)
    house.catalogue = [ActionInfo(a, a, f, "none") for a, f in CATALOGUE.items() if a != "todo.get_items"]
    house.catalogue.append(ActionInfo("todo.get_items", "Items", {}, "only"))
    house.returns = {"todo.get_items": {"todo.inbox": {"items": [{"summary": "milk"}]}}}
    return house


def house_tools(house: MemoryHouse, consequential: tuple[str, ...] = ()) -> HouseTools:
    return HouseTools(house, house_rules(), house_look_config.load(), house_state_config.load(), household_id=HOUSEHOLD,
                      consequential=consequential)


def do(action: str, entity: str, data: Mapping[str, object] | None = None) -> ToolCall:
    arguments: dict[str, object] = {"action": action, "ids": [entity]}
    if data is not None:
        arguments["data"] = json.dumps(data)
    return ToolCall(f"d-{action}-{entity}", "house_do", arguments)


def performed(house: MemoryHouse) -> list[str]:
    return [d[2] for d in house.done]
