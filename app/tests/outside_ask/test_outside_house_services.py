"""`house_ask` on an action whose response only a service writes (Google's distance, a forecast) leaves the turn
untainted; the scripts that return business names or recipe text, and any action not named, still taint it."""

from ashley.home_assistant.house import ActionInfo
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_tools import HouseTools
from house_settings_support import house_rules
from house_double_support import MemoryHouse, state
from outside_ask_support import CONVERSATION, STANDING, TURN, Memory, Tainted, asked, run
from ashley import services
from ashley.senses.proposals import Proposals
from ashley.tools.outside import Outside

ACTIONS = ("script.drive_time", "weather.get_forecasts", "script.find_person", "script.find_recipe",
           "calendar.get_events")


def stack() -> Outside:
    house = MemoryHouse(things=[state("weather.home", "Home", "sunny", None), state("calendar.home", "Home", "off", None),
                                state("script.drive_time", "Travel", "off", None)])
    house.catalogue = [ActionInfo(a, a, {}, "only") for a in ACTIONS]
    house.returns = {a: {"weather.home": {"forecast": []}} for a in ACTIONS}
    tools = HouseTools(house, house_rules(), house_look_config.load(), house_state_config.load())
    services.register(Proposals, Memory())
    return Outside(tools, STANDING, (CONVERSATION, TURN), Tainted())


def tainted_by(action: str, *ids: str) -> str | None:
    outside = stack()

    async def go() -> None:
        await outside.call(asked("house_ask", action=action, ids=list(ids)))

    run(go())
    return outside.tainted


def test_a_distance_and_a_forecast_leave_the_turn_untainted() -> None:
    assert tainted_by("script.drive_time", "script.drive_time") is None
    assert tainted_by("weather.get_forecasts", "weather.home") is None


def test_a_script_that_returns_business_names_or_recipe_text_taints_the_turn() -> None:
    for action in ("script.find_person", "script.find_recipe"):
        assert tainted_by(action, "script.drive_time") == "house_ask", action


def test_a_calendar_still_taints_the_turn() -> None:
    assert tainted_by("calendar.get_events", "calendar.home") == "house_ask"
