"""`house_ask` taints a turn by the action it asked for: a list's items are written by the household and do not, a
calendar's events and any action not named in `home_assistant.json` do, and a change after a taint is held."""

from ashley.home_assistant.house import ActionInfo
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_tools import HouseTools
from house_settings_support import house_rules
from house_double_support import MemoryHouse, state
from outside_ask_support import CONVERSATION, STANDING, TURN, Memory, Tainted, asked, run
from ashley import services
from ashley.inference.model import ToolCall
from ashley.senses.proposals import Proposals
from ashley.tools.outside import Outside


def stack() -> tuple[Outside, MemoryHouse, Tainted]:
    house = MemoryHouse(things=[state("todo.inbox", "Inbox", "2", None), state("calendar.home", "Home", "off", None)])
    house.catalogue = [ActionInfo("todo.get_items", "Items", {}, "only"), ActionInfo("calendar.get_events", "Events", {}, "only"),
                       ActionInfo("media_player.browse_media", "Browse", {}, "only"),
                       ActionInfo("todo.remove_item", "Remove", {"item": "which"}, "none")]
    house.returns = {"todo.get_items": {"todo.inbox": {"items": [{"summary": "milk"}]}},
                     "calendar.get_events": {"calendar.home": {"events": []}},
                     "media_player.browse_media": {"calendar.home": {"children": []}}}
    tools = HouseTools(house, house_rules(), house_look_config.load(), house_state_config.load())
    services.register(Proposals, Memory())
    steps = Tainted()
    return Outside(tools, STANDING, (CONVERSATION, TURN), steps), house, steps


def ask(action: str, name: str) -> ToolCall:
    return asked("house_ask", action=action, ids=[name])


def test_reading_the_households_list_leaves_the_turn_untainted_and_a_removal_runs() -> None:
    async def go() -> None:
        outside, house, steps = stack()
        read = await outside.call(ask("todo.get_items", "todo.inbox"))
        assert not read.is_error and outside.tainted is None and steps.seen == []
        done = await outside.call(asked("house_do", "c2", action="todo.remove_item", ids=["todo.inbox"],
                                        data='{"item": "milk"}'))
        assert "held" not in done.content and ("perform", "action", "todo.remove_item", ("todo.inbox",),
                                               {"item": "milk"}) in house.done

    run(go())


def test_reading_a_calendar_taints_the_turn_and_a_removal_is_held() -> None:
    async def go() -> None:
        outside, house, steps = stack()
        await outside.call(ask("calendar.get_events", "calendar.home"))
        assert outside.tainted == "house_ask" and steps.seen == ["house_ask"]
        held = await outside.call(asked("house_do", "c2", action="todo.remove_item", ids=["todo.inbox"]))
        assert "held" in held.content and not [d for d in house.done if d[2] == "todo.remove_item"]

    run(go())


def test_an_action_the_config_does_not_name_taints_the_turn() -> None:
    async def go() -> None:
        outside, _, _ = stack()
        await outside.call(ask("media_player.browse_media", "calendar.home"))
        assert outside.tainted == "house_ask"

    run(go())
