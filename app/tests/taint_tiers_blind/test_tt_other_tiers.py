"""The non-house examples of section 2 through `Outside`: reminders and watches that carry no tools, and a bench edit,
run in a tainted turn; changing or cancelling a reminder is judged and, under the Null judge, held."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ashley.inference.model import ToolCall
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.model import Owner
from taint_tiers_blind_support import Tiered, held_tools, reminder_tools, scenario, taint_the_turn, watch_tools

DENVER = ZoneInfo("America/Denver")


def when() -> str:
    return (datetime.now(DENVER) + timedelta(days=3)).strftime("%Y-%m-%dT09:00")


def remind(what: str = "Water the plants.") -> ToolCall:
    return ToolCall("r1", "remind", {"for": "Alana", "at": when(), "what": what})


def test_a_reminder_without_tools_is_made_in_a_tainted_turn(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        o = taint_the_turn(reminder_tools(t), t.w, "look_up")
        got = await o.call(remind())
        assert not got.is_error and "held" not in got.content, got.content
        assert len(await t.wakes.reminders(t.home, t.alana)) == 1 and await t.w.held() == []

    scenario(db_url, body)


def test_a_reminder_is_made_in_an_untainted_turn_too(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        got = await taint_the_turn(reminder_tools(t), t.w, None).call(remind())
        assert not got.is_error and len(await t.wakes.reminders(t.home, t.alana)) == 1

    scenario(db_url, body)


def test_changing_a_reminder_in_a_tainted_turn_is_held_and_the_reminder_is_unchanged(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        made = await taint_the_turn(reminder_tools(t), t.w, None).call(remind())
        rid = json.loads(made.content)["id"]
        o = taint_the_turn(reminder_tools(t), t.w, "look_up")
        got = await o.call(ToolCall("c1", "change_reminder", {"id": rid, "what": "Something else."}))
        assert "held" in got.content
        [s] = await t.wakes.reminders(t.home, t.alana)
        assert s.reminder.brief == "Water the plants." and held_tools(await t.w.held()) == ["change_reminder"]

    scenario(db_url, body)


def test_cancelling_a_reminder_in_a_tainted_turn_is_held_and_it_still_fires(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        made = await taint_the_turn(reminder_tools(t), t.w, None).call(remind())
        rid = json.loads(made.content)["id"]
        o = taint_the_turn(reminder_tools(t), t.w, "look_up")
        got = await o.call(ToolCall("c1", "cancel_reminder", {"id": rid}))
        assert "held" in got.content and len(await t.wakes.reminders(t.home, t.alana)) == 1
        assert held_tools(await t.w.held()) == ["cancel_reminder"]

    scenario(db_url, body)


def test_a_watch_without_tools_is_started_in_a_tainted_turn_and_unwatch_runs(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        o = taint_the_turn(watch_tools(t), t.w, "look_up")
        got = await o.call(ToolCall("w1", "watch", {"kind": "claude_session", "target": "s1"}))
        assert not got.is_error and "held" not in got.content, got.content
        assert len(await t.watches.live(t.home, t.alana)) == 1
        gone = await o.call(ToolCall("w2", "unwatch", {"kind": "claude_session", "target": "s1"}))
        assert not gone.is_error and "held" not in gone.content
        assert await t.watches.live(t.home, t.alana) == () and await t.w.held() == []

    scenario(db_url, body)


def test_a_bench_edit_runs_in_a_tainted_turn(db_url: str) -> None:
    async def body(t: Tiered) -> None:
        bench = await t.shop.open(Owner(t.home, t.alana), "shed")
        o = taint_the_turn(BenchTools(t.home, t.alana, bench.id), t.w, "look_up")
        added = await o.call(ToolCall("a", "bench_add", {"kind": "note", "title": "Wood", "body": "pine"}))
        assert not added.is_error and "held" not in added.content, added.content
        piece = json.loads(added.content)["piece_id"]
        await o.call(ToolCall("r", "bench_read_piece", {"piece_id": piece}))
        edited = await o.call(ToolCall("e", "bench_edit", {"piece_id": piece, "base_version": 1, "title": "Wood",
                                                         "body": "oak"}))
        assert not edited.is_error and "held" not in edited.content, edited.content
        (found,) = (await t.shop.read(Owner(t.home, t.alana), bench.id)).pieces
        assert found.text.body == "oak" and await t.w.held() == []

    scenario(db_url, body)
