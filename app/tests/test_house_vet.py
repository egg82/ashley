"""The view of a `house_do` call the judge is given (`ashley.tools.house_vet`): the action when the house offers it, the
household's own names of the things it resolves to, and the call's data as a length; nothing the model wrote."""

import asyncio
import json
from collections.abc import Mapping

from ashley.home_assistant.house import ActionInfo
from ashley.inference.model import ToolCall
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_tools import HouseTools
from house_double_support import MemoryHouse, state
from house_settings_support import house_rules

PLANT = "PLANTED-by-a-stranger"


def the_house() -> MemoryHouse:
    house = MemoryHouse(things=[state("light.porch", "Porch", "off"), state("lock.front", "Front door", "locked")])
    house.catalogue = [ActionInfo(a, a, {}, "none") for a in ("light.turn_on", "lock.unlock", "lock.lock")]
    return house


def house_tools(house: MemoryHouse) -> HouseTools:
    return HouseTools(house, house_rules(), house_look_config.load(), house_state_config.load(), household_id=1)


def do(action: str, entity: str, data: Mapping[str, object] | None = None) -> ToolCall:
    arguments: dict[str, object] = {"action": action, "ids": [entity]}
    if data is not None:
        arguments["data"] = json.dumps(data)
    return ToolCall("c", "house_do", arguments)


def view_of(call: ToolCall) -> dict[str, str]:
    got = asyncio.run(house_tools(the_house()).vetted(call, ("unlock the front door",)))
    assert got is not None and got.view is not None and got.ask is None
    return dict(got.view.fields)


def test_a_call_shows_the_offered_action_the_names_of_what_it_resolves_to_and_the_data_as_a_length() -> None:
    fields = view_of(do("lock.unlock", "lock.front", {"code": PLANT}))
    assert fields["action"] == "lock.unlock" and fields["things"] == "Front door"
    assert fields["data"].startswith("<text, ") and PLANT not in repr(fields)


def test_an_action_the_house_does_not_offer_is_a_length() -> None:
    fields = view_of(do(f"lock.{PLANT}", "lock.front"))
    assert fields["action"] == f"<text, {len(f'lock.{PLANT}')} chars>" and PLANT not in repr(fields)


def test_a_name_is_resolved_to_the_house_s_name_and_an_id_the_house_lacks_to_none_found() -> None:
    named = view_of(ToolCall("c", "house_do", {"action": "light.turn_on", "name": "porch"}))
    assert named["things"] == "Porch"
    missing = view_of(ToolCall("c", "house_do", {"action": "light.turn_on", "ids": [PLANT]}))
    assert missing["things"] == "none found in the house" and PLANT not in repr(missing)


def test_a_call_whose_arguments_cannot_be_read_shows_only_that() -> None:
    fields = view_of(ToolCall("c", "house_do", {"action": ["not", "text"], "name": PLANT}))
    assert fields == {"action": "<unreadable>"}


def test_another_tool_has_no_house_view() -> None:
    assert asyncio.run(house_tools(the_house()).vetted(ToolCall("c", "house_state", {}), ("x",))) is None
