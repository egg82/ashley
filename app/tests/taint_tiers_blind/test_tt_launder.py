"""Laundering (design 2.1): what a tainted turn writes freely is marked, so a later untainted turn does not read it as
household-written. A reminder or watch fires a turn whose origin is `inherited`; a list a tainted turn wrote to reads
back as outside for a while; a bench piece it edited reads back as outside."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ashley.channels.model import Inbound
from ashley.channels.wake import reminder_turn, watch_turn
from ashley.criteria.record import Change
from ashley.inference.model import ToolCall
from ashley.people.model import Person
from ashley.tools.bench_tools import BenchTools
from ashley.watches.rows import changed_wake
from ashley.senses.wakes import WatchWake
from ashley.workshop.model import Owner
from taint_tiers_blind_support import (reminder_tools, scenario, taint_the_turn, Tiered, watch_tools)
from taint_tiers_blind_house_support import do, house_tools, performed, the_house
from watch_job_support import NOW
from watch_session_support import SESSION

DENVER = ZoneInfo("America/Denver")
YEAR = 400


def remind() -> ToolCall:
    at = (datetime.now(DENVER) + timedelta(days=3)).strftime("%Y-%m-%dT09:00")
    return ToolCall("r1", "remind", {"for": "Alana", "at": at, "what": "Do the thing."})


def watch_wake() -> WatchWake:
    before, after = {"status": "working", "seq": 1001}, {"status": "done", "seq": 1002}
    return WatchWake(1, 7, 1, "changed", changed_wake(1, NOW, False, (Change(SESSION, "changed", before, after),)))


async def fires_as(t: Tiered, inbound: Inbound) -> tuple[list[str], list[str]]:
    """What a turn that starts as `inbound` does with a lamp (tier b) and a lock (tier c) over the real house."""
    house = the_house()
    o = t.w.wrap(house_tools(house), inbound)
    await o.call(do("light.turn_on", "light.porch"))
    await o.call(do("lock.unlock", "lock.front"))
    return performed(house), [str(a["action"]) for _, a in await t.w.held()]


def test_a_reminder_made_in_a_tainted_turn_fires_a_turn_with_origin_inherited_and_tiers_apply_again(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        await taint_the_turn(reminder_tools(t), t.w, "look_up").call(remind())
        [made] = await t.wakes.reminders(t.home, t.alana)
        assert made.reminder.taint is not None
        fired = reminder_turn.inbound(made.id, made.reminder, Person(t.alana, t.home, "Alana"), Person(t.alana, t.home, "Alana"))
        assert fired.taint == "inherited"
        assert await fires_as(t, fired) == (["light.turn_on"], ["lock.unlock"])

    scenario(db_url, body)


def test_a_reminder_made_in_an_untainted_turn_fires_untainted(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        await taint_the_turn(reminder_tools(t), t.w, None).call(remind())
        [made] = await t.wakes.reminders(t.home, t.alana)
        assert made.reminder.taint is None
        alana = Person(t.alana, t.home, "Alana")
        assert reminder_turn.inbound(made.id, made.reminder, alana, alana).taint is None

    scenario(db_url, body)


def test_a_watch_started_in_a_tainted_turn_wakes_a_turn_with_origin_inherited(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        o = taint_the_turn(watch_tools(t), t.w, "look_up")
        await o.call(ToolCall("w1", "watch", {"kind": "claude_session", "target": "s1"}))
        [row] = await t.watches.live(t.home, t.alana)
        assert row.taint is not None
        assert watch_turn.inbound(9, row, watch_wake(), False).taint == "inherited"

    scenario(db_url, body)


def test_a_watch_started_in_an_untainted_turn_wakes_untainted_for_a_kind_that_reads_no_outside_text(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        await taint_the_turn(watch_tools(t), t.w, None).call(ToolCall("w1", "watch", {"kind": "claude_session", "target": "s1"}))
        [row] = await t.watches.live(t.home, t.alana)
        assert row.taint is None and watch_turn.inbound(9, row, watch_wake(), False).taint is None

    scenario(db_url, body)


def test_a_list_written_from_a_tainted_turn_reads_back_as_outside_and_untainted_after_keep_s(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        house = the_house()
        ask = ToolCall("g", "house_ask", {"action": "todo.get_items", "ids": ["todo.inbox"]})
        before = taint_the_turn(house_tools(house), t.w, None)
        await before.call(ask)
        assert before.tainted is None, "control: the household's list reads as household-written"
        await taint_the_turn(house_tools(house), t.w, "look_up").call(do("todo.add_item", "todo.inbox", {"item": "x"}))
        assert t.writes() == ["todo.inbox"]
        later = taint_the_turn(house_tools(house), t.w, None)
        await later.call(ask)
        assert later.tainted == "house_ask"
        t.exec("UPDATE outside_writes SET at = now() - make_interval(days => %s)", (YEAR,))
        after = taint_the_turn(house_tools(house), t.w, None)
        await after.call(ask)
        assert after.tainted is None

    scenario(db_url, body)


def test_a_list_written_from_an_untainted_turn_is_not_marked(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        house = the_house()
        await taint_the_turn(house_tools(house), t.w, None).call(do("todo.add_item", "todo.inbox", {"item": "x"}))
        assert performed(house) == ["todo.add_item"] and t.writes() == []

    scenario(db_url, body)


async def piece_read_outside(t: Tiered, tainted: str | None) -> bool:
    bench = await t.shop.open(Owner(t.home, t.alana), "shed")
    writer = taint_the_turn(BenchTools(t.home, t.alana, bench.id), t.w, tainted)
    added = await writer.call(ToolCall("a", "bench_add", {"kind": "note", "title": "Wood", "body": "pine"}))
    piece = json.loads(added.content)["piece_id"]
    await writer.call(ToolCall("r", "bench_read_piece", {"piece_id": piece}))
    await writer.call(ToolCall("e", "bench_edit", {"piece_id": piece, "base_version": 1, "title": "Wood", "body": "oak"}))
    reader = BenchTools(t.home, t.alana, bench.id)
    one = await reader.call(ToolCall("p", "bench_read_piece", {"piece_id": piece}))
    whole = await reader.call(ToolCall("b", "bench_read", {}))
    assert one.outside == whole.outside and not one.is_error
    return bool(one.outside)


def test_a_piece_edited_in_a_tainted_turn_is_outside_when_read_later(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        assert await piece_read_outside(t, "look_up") is True

    scenario(db_url, body)


def test_a_piece_edited_in_an_untainted_turn_is_not_outside(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        assert await piece_read_outside(t, None) is False

    scenario(db_url, body)
