"""`house_roster.roster` and the shipped guidance: the devices Home Assistant exposes, area by area, under her own text."""

from ashley.tools import home_assistant_config
from ashley.tools.house_entities import Entity
from ashley.tools.house_roster import roster
from house_support import Device, device, entities_of


def entities(*devices: Device) -> tuple[Entity, ...]:
    return entities_of(list(devices))


def test_each_area_is_a_line_of_its_devices_with_aliases_and_the_unplaced_last() -> None:
    got = roster(entities(
        device("Zed Lamp", "light", "on", "Zeta"),
        device("Speaker", "media_player", "idle"),
        device("Kitchen Light", "light", "off", "Kitchen"),
        device("Shopping List, Shopping", "todo", "3", "Kitchen"),
        device("Oven", "switch", "off", "kitchen")))
    assert got.split("\n") == [
        "Kitchen: Kitchen Light (light), Shopping List / Shopping (todo)",
        "kitchen: Oven (switch)",
        "Zeta: Zed Lamp (light)",
        "(no area): Speaker (media_player)"]


def test_no_devices_is_no_text() -> None:
    assert roster(()) == ""


def test_the_shipped_guidance_is_her_own_short_text_for_the_house_tools() -> None:
    guidance = home_assistant_config.load().guidance
    assert all(name in guidance for name in ("house_state", "house_find", "house_do", "house_ask", "house_history"))
    assert "GetLiveContext" not in guidance and "intent__" not in guidance
    assert len(guidance.split("\n")) <= 6
