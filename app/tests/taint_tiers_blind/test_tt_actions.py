"""What a tainted turn did on its own (design 3.4): a row in `outside_actions` for each tier b change it ran, with no
argument text beside the summary the code wrote, pruned past retention by the writer; and the block under her reply that
lists it."""

import json

from ashley.tools.outside import Outside
from receipts_shown import held_text, shown
from taint_tiers_blind_support import (OUTSIDE_RETENTION_DAYS, PLANT, scenario, taint_the_turn, TIER_B, Tiered)
from taint_tiers_blind_house_support import do, house_tools, the_house

LAMP = ("light.turn_on", "light.porch")


async def run_tainted(t: Tiered, *calls: tuple[str, str], tainted: str | None = "look_up",
                      turn: int | None = None) -> Outside:
    o = taint_the_turn(house_tools(the_house()), t.w, tainted, turn=turn)
    for action, entity in calls:
        await o.call(do(action, entity, {"item": PLANT} if action.startswith("todo") else None))
    return o


def test_a_tier_b_change_in_a_tainted_turn_is_recorded_with_its_tool_tier_turn_and_time(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        turn = t.w.turn()
        await run_tainted(t, LAMP, turn=turn)
        [row] = t.actions()
        assert (row["tool"], row["tier"], row["turn_id"], row["conversation_id"]) == ("house_do", TIER_B, turn, t.w.chat)
        assert row["at"] is not None

    scenario(db_url, body)


def test_the_row_carries_no_argument_text_not_even_in_the_summary(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        await run_tainted(t, ("todo.add_item", "todo.inbox"))
        [row] = t.actions()
        assert PLANT not in json.dumps(row) and row["summary"], "the summary is written, and holds none of the text"
        o = await run_tainted(t, ("todo.add_item", "todo.inbox"))
        assert PLANT not in shown(await o.receipts())

    scenario(db_url, body)


def test_nothing_is_recorded_for_an_untainted_turn_a_read_or_a_held_call(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        await run_tainted(t, LAMP, tainted=None)
        await run_tainted(t, ("lock.unlock", "lock.front"))
        assert t.actions() == []

    scenario(db_url, body)


def test_each_tier_b_change_is_one_row(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        await run_tainted(t, LAMP, ("fan.turn_on", "fan.den"), ("lock.unlock", "lock.front"))
        assert sorted(r["tool"] for r in t.actions()) == ["house_do", "house_do"]

    scenario(db_url, body)


def seed(t: Tiered, age_days: int, tool: str) -> None:
    t.exec("INSERT INTO outside_actions (household_id, person_id, conversation_id, turn_id, tool, summary, tier, "
           "decision, reason, explanation, at) VALUES (%s, %s, %s, %s, %s, 's', %s, 'run', 'unclear', 'e', "
           "now() - make_interval(days => %s))", (t.home, t.alana, t.w.chat, t.w.turn(), tool, TIER_B, age_days))


def test_the_writer_prunes_rows_past_retention_and_keeps_those_inside_it(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        seed(t, OUTSIDE_RETENTION_DAYS + 30, "old_tool")
        seed(t, OUTSIDE_RETENTION_DAYS - 30, "recent_tool")
        assert sorted(r["tool"] for r in t.actions()) == ["old_tool", "recent_tool"], "control: both are there"
        await run_tainted(t, LAMP)
        assert sorted(r["tool"] for r in t.actions()) == ["house_do", "recent_tool"]

    scenario(db_url, body)


def test_a_turn_that_ran_only_a_runs_tier_change_shows_nothing_beside_her_reply(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        o = await run_tainted(t, LAMP)
        assert await o.receipts() is None

    scenario(db_url, body)


def test_the_receipts_list_what_waits_and_not_the_runs_tier_change(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        o = await run_tainted(t, LAMP, ("lock.unlock", "lock.front"))
        receipts = await o.receipts()
        assert receipts is not None and receipts.done == ()
        assert "light.turn_on" not in held_text(receipts) and "lock.unlock" in held_text(receipts)

    scenario(db_url, body)


def test_no_receipts_when_the_turn_changed_nothing_or_was_not_tainted(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        assert await (await run_tainted(t, tainted="look_up")).receipts() is None
        assert await (await run_tainted(t, LAMP, tainted=None)).receipts() is None

    scenario(db_url, body)
