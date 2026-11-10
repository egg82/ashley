"""`house_ask` on a list untaints the turn only when every list it named is one the household alone writes, as
`home_assistant.json` names them: a list a job fills with web page titles keeps tainting."""

from ashley.home_assistant.house import ActionInfo
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_tools import HouseTools
from house_settings_support import house_rules
from house_double_support import MemoryHouse, state
from outside_ask_support import CONVERSATION, STANDING, TURN, Memory, Tainted, asked, run
from ashley import services
from ashley.senses.proposals import Proposals
from ashley.tools.outside import Outside

LISTS = ("todo.inbox", "todo.groceries", "todo.to_do_list", "todo.weekly_shopping")


def stack() -> Outside:
    house = MemoryHouse(things=[state(i, i, "1", None) for i in LISTS])
    house.catalogue = [ActionInfo("todo.get_items", "Items", {}, "only")]
    house.returns = {"todo.get_items": {i: {"items": [{"summary": "x"}]} for i in LISTS}}
    tools = HouseTools(house, house_rules(), house_look_config.load(), house_state_config.load())
    services.register(Proposals, Memory())
    return Outside(tools, STANDING, (CONVERSATION, TURN), Tainted())


def read(*ids: str) -> Outside:
    outside = stack()
    run(_ask(outside, ids))
    return outside


async def _ask(outside: Outside, ids: tuple[str, ...]) -> None:
    await outside.call(asked("house_ask", action="todo.get_items", ids=list(ids)))


def test_a_list_the_household_alone_writes_leaves_the_turn_untainted() -> None:
    for ids in (("todo.inbox",), ("todo.groceries",), ("todo.weekly_shopping",),
                ("todo.inbox", "todo.groceries")):
        assert read(*ids).tainted is None, ids


def test_the_list_a_job_fills_with_page_titles_taints_the_turn() -> None:
    assert read("todo.to_do_list").tainted == "house_ask"


def test_one_list_not_named_among_several_taints_the_turn() -> None:
    assert read("todo.inbox", "todo.to_do_list").tainted == "house_ask"
