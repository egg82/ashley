"""A list a tainted turn writes reads back as outside (design 2.1, A.2): a `todo.add_item` that ran after outside words were
read is noted, and a later `house_ask` of that list taints its turn though the household alone fills the list, while a list
nobody tainted wrote does not; an untainted turn's write is not noted; and a record that cannot be read leaves the read
outside."""

from ashley import services
from ashley.home_assistant.house import ActionInfo
from ashley.senses.outside_record import OutsideRecord
from ashley.tools import house_look_config, house_state_config
from ashley.tools.house_tools import HouseTools
from ashley.tools.outside import Outside
from house_settings_support import house_rules
from house_double_support import MemoryHouse, state
from outside_ask_support import CONVERSATION, HOUSEHOLD, STANDING, TURN, Memory, Tainted, asked, run
from ashley.senses.proposals import Proposals

LISTS = ("todo.inbox", "todo.groceries")


def stack(turn: int = TURN, tainted: str | None = None) -> tuple[Outside, MemoryHouse]:
    house = MemoryHouse(things=[*(state(i, i, "1", None) for i in LISTS), state("calendar.home", "Home", "off", None)])
    house.catalogue = [ActionInfo("todo.get_items", "Items", {}, "only"), ActionInfo("calendar.get_events", "Events", {}, "only"),
                       ActionInfo("todo.add_item", "Add", {"item": "which"}, "none")]
    house.returns = {"todo.get_items": {i: {"items": [{"summary": "x"}]} for i in LISTS},
                     "calendar.get_events": {"calendar.home": {"events": []}}}
    tools = HouseTools(house, house_rules(), house_look_config.load(), house_state_config.load(), "", HOUSEHOLD)
    services.register(Proposals, Memory())
    return Outside(tools, STANDING, (CONVERSATION, turn), Tainted(), tainted), house


async def add_item(outside: Outside, entity: str) -> None:
    got = await outside.call(asked("house_do", action="todo.add_item", ids=[entity], data='{"item": "milk"}'))
    assert not got.is_error and "held" not in got.content


async def read_list(outside: Outside, entity: str) -> None:
    await outside.call(asked("house_ask", "r", action="todo.get_items", ids=[entity]))


def test_a_list_a_tainted_turn_wrote_taints_the_turn_that_reads_it_and_another_list_does_not() -> None:
    async def go() -> None:
        writer, house = stack()
        await writer.call(asked("house_ask", "c0", action="calendar.get_events", ids=["calendar.home"]))
        assert writer.tainted == "house_ask"
        await add_item(writer, "todo.inbox")
        assert "todo.add_item" in [d[2] for d in house.done]
        assert await services.get(OutsideRecord).written(HOUSEHOLD, ["todo.inbox"])
        reader, _ = stack(TURN + 1)
        await read_list(reader, "todo.inbox")
        assert reader.tainted == "house_ask"
        clean, _ = stack(TURN + 2)
        await read_list(clean, "todo.groceries")
        assert clean.tainted is None

    run(go())


def test_a_write_from_an_untainted_turn_is_not_noted() -> None:
    async def go() -> None:
        writer, _ = stack()
        await add_item(writer, "todo.inbox")
        reader, _ = stack(TURN + 1)
        await read_list(reader, "todo.inbox")
        assert reader.tainted is None

    run(go())


def test_a_record_that_cannot_be_read_leaves_a_household_list_outside_and_a_write_still_runs() -> None:
    async def go() -> None:
        services.unregister(OutsideRecord)
        reader, _ = stack()
        await read_list(reader, "todo.inbox")
        assert reader.tainted == "house_ask"
        writer, house = stack(TURN + 1, "mail_read")
        await add_item(writer, "todo.inbox")
        assert [d[2] for d in house.done] == ["todo.add_item"]

    run(go())
