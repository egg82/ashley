"""Her watch tools over a real database, a fake bridge and the real `claude_session` kind: `watch` reads the target
once and stores it as the baseline, `unwatch` stops it by what she watched, `watches` lists the speaker's own; a watch
that names a tool that acts is only proposed and is armed by `arm_reminder` in a later turn; and the tools are offered
only where the reply reaches the speaker alone and a bridge is connected."""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from ashley import services
from ashley.channels import turn_tools
from ashley.channels.model import Inbound
from ashley.connections.connections import Connections
from ashley.criteria.items import ItemPredicate
from ashley.db.pool import PoolDatabase
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Session
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.logs import Logfmt
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import REMINDERS, WatchSchedule, check, encode
from ashley.senses.proposals import Proposals
from ashley.senses.wakes import Reminder
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Tools
from ashley.tools.watches import WatchTools
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar
from money_support import HeldConnections
from test_reminder_turn import Home
from test_watches_claude_session import BASE, FakeBridge
from wake_support import Switchboard

SESSIONS = (Session("s1", "build", "/d", "working", 4, None), Session("s2", "docs", "/d", "done", 9, None))


@dataclass
class World:
    url: str
    home: int
    alana: int
    sam: int
    bridge: FakeBridge

    def tools(self, who: int | None = None, turn: tuple[int, int] | None = None,
              board: Tools | None = None) -> WatchTools:
        kept = board or Switchboard()
        return WatchTools(self.home, who or self.alana, turn=turn, usable=lambda: kept)

    def rows(self, query: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = scalar(self.url, f"SELECT coalesce(json_agg(t), '[]'::json) FROM ({query}) t")
        return found


@asynccontextmanager
async def world(url: str, connected: bool = True, sessions: tuple[Session, ...] = SESSIONS) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    alana, sam = person(url, home, "Alana"), person(url, home, "Sam")
    held, bridge = HeldConnections(), FakeBridge(sessions)
    if connected:
        held.connect(home, BASE, "tok", "herdr", alana)
    wired = {People: Home(Household(home, "home", "America/Denver", "",
                                    (Person(alana, home, "Alana"), Person(sam, home, "Sam")))),
             Tools: Switchboard(), Watches: PostgresWatches(db), Proposals: PostgresProposals(db), Connections: held, Bridge: bridge}
    for interface, provider in wired.items():
        services.register(interface, provider)
    try:
        yield World(url, home, alana, sam, bridge)
    finally:
        for interface in wired:
            services.unregister(interface)
        await db.close()


async def call(tools: Tools, name: str, args: dict[str, object]) -> ToolResult:
    return await tools.call(ToolCall("c", name, args))


def properties_of(spec: ToolSpec) -> dict[str, Any]:
    parameters: dict[str, Any] = dict(spec.parameters)
    properties: dict[str, Any] = parameters["properties"]
    return properties


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    return json.loads(result.content)


def stored(w: World) -> list[dict[str, Any]]:
    return w.rows("SELECT kind, target, label, state, reason, tools, until_clauses, baseline, armed_by, bench_id "
                  "FROM watches ORDER BY id")


def test_watch_reads_the_target_once_and_stores_it_as_the_baseline_with_the_kinds_defaults(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = body(await call(w.tools(), "watch", {"kind": "claude_session", "target": "s1"}))
            assert got["armed"] is True and got["label"] == "build"
            assert got["now"] == {"s1": {"status": "working", "seq": 4}}
            ends = datetime.strptime(str(got["ends"]), "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo("America/Denver"))
            assert abs((ends - datetime.now(UTC) - timedelta(hours=24)).total_seconds()) < 120
            [row] = stored(w)
            assert row == {"kind": "claude_session", "target": "s1", "label": "build", "state": "armed",
                           "reason": None, "tools": None, "until_clauses": None, "armed_by": "ashley",
                           "baseline": {"s1": {"status": "working", "seq": 4}}, "bench_id": None}
            assert w.bridge.asked == 2   # the read, and the label
    run(go())


def test_the_expiry_is_hours_from_now_and_defaults_to_the_kinds(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await call(w.tools(), "watch", {"kind": "claude_session", "target": "s1"})
            await call(w.tools(), "watch", {"kind": "claude_session", "target": "s2", "hours": 2})
            long, short = (scalar(db_url, "SELECT extract(epoch FROM expires_at - now()) FROM watches WHERE target = %s",
                                  (t,)) for t in ("s1", "s2"))
            assert 23.9 * 3600 < long <= 24 * 3600 and 1.9 * 3600 < short <= 2 * 3600
    run(go())


def test_until_gone_is_stored_as_the_clause_and_a_field_the_kind_does_not_track_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            args: dict[str, object] = {"kind": "claude_session", "target": "s1"}
            made = body(await call(w.tools(), "watch", {**args, "until": [[{"kind": "gone"}]]}))
            assert made["until"] == [["the item is gone"]]
            [row] = stored(w)
            assert row["until_clauses"] == [[{"kind": "gone", "negate": False}]]
            bad = await call(w.tools(), "watch", {**args, "target": "s2", "until": [[{"kind": "equals", "field": "colour",
                                                                                    "value": "red"}]]})
            assert bad.is_error and bad.content.startswith("bad_arguments")
            assert len(stored(w)) == 1
    run(go())


@pytest.mark.parametrize("args", [
    {"hours": 0}, {"hours": 169}, {"hours": True}, {"hours": "3"}, {"kind": "mystery"}, {"target": ""}, {"target": 4},
    {"until": []}, {"until": "gone"}, {"until": [["gone"]]}, {"until": [[{"kind": "gone", "field": "status"}]]},
    {"until": [[{"kind": "equals", "field": "status"}]]}, {"until": [[{"kind": "gone"}]] * 5},
    {"until": [[{"kind": "gone"}] * 7]}, {"surprise": 1}])
def test_bad_arguments_store_nothing(db_url: str, args: dict[str, object]) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            got = await call(w.tools(), "watch", {"kind": "claude_session", "target": "s1", **args})
            assert got.is_error and got.content.startswith("bad_arguments")
            assert stored(w) == []
    run(go())


def test_a_target_the_bridge_does_not_list_is_not_found_and_an_unreachable_bridge_says_so(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            missing = await call(w.tools(), "watch", {"kind": "claude_session", "target": "nope"})
            assert missing.is_error and missing.content.startswith("not_found")
            w.bridge.fail = "herdr_unavailable"
            down = await call(w.tools(), "watch", {"kind": "claude_session", "target": "s1"})
            assert down.is_error and down.content.startswith("unreachable")
            assert stored(w) == []
    run(go())


def test_watching_the_same_target_again_updates_the_watch_it_does_not_add_one(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            args: dict[str, object] = {"kind": "claude_session", "target": "s1"}
            first = body(await call(w.tools(), "watch", args))
            second = body(await call(w.tools(), "watch", {**args, "until": [[{"kind": "gone"}]]}))
            assert (first["new"], second["new"]) == (True, False) and len(stored(w)) == 1
    run(go())


def test_unwatch_ends_the_watch_by_kind_and_target_and_a_second_is_not_found(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await call(w.tools(), "watch", {"kind": "claude_session", "target": "s1"})
            await call(w.tools(), "watch", {"kind": "claude_session", "target": "s2"})
            assert body(await call(w.tools(), "unwatch", {"kind": "claude_session", "target": "s1"})) == {"stopped": True}
            again = await call(w.tools(), "unwatch", {"kind": "claude_session", "target": "s1"})
            assert again.is_error and again.content.startswith("not_found")
            assert [(r["target"], r["state"], r["reason"]) for r in stored(w)] == [
                ("s1", "ended", "disarmed"), ("s2", "armed", None)]
    run(go())


def test_watches_lists_only_the_speakers_live_watches_with_why_a_paused_one_paused(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await call(w.tools(), "watch", {"kind": "claude_session", "target": "s1", "until": [[{"kind": "gone"}]]})
            await call(w.tools(), "watch", {"kind": "claude_session", "target": "s2"})
            await call(w.tools(), "unwatch", {"kind": "claude_session", "target": "s2"})
            await call(w.tools(), "watch", {"kind": "claude_session", "target": "s2"})
            scalar(db_url, "UPDATE watches SET state = 'paused', reason = 'unreachable', failures = 3 WHERE target = 's2' AND state = 'armed' "
                           "RETURNING 1")
            shown = body(await call(w.tools(), "watches", {}))["watches"]
            assert [(s["target"], s["label"], s["until"], s.get("paused")) for s in shown] == [
                ("s1", "build", [["the item is gone"]], None), ("s2", "docs", None, "unreachable")]
            assert all(s["kind"] == "claude_session" and s["expires"] for s in shown)
            sam = body(await call(w.tools(who=w.sam), "watches", {}))
            assert sam == {"watches": []}
    run(go())


def test_nothing_is_offered_without_a_connected_bridge_and_the_watches_tool_reads(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, connected=False) as w:
            assert (await w.tools().catalogue()).specs == ()
            gone = await call(w.tools(), "watch", {"kind": "claude_session", "target": "s1"})
            assert gone.is_error and gone.content.startswith("bad_arguments")
        async with world(db_url) as w:
            specs = {s.name: s for s in (await w.tools().catalogue()).specs}
            assert set(specs) == {"watch", "unwatch", "watches"}
            assert [n for n, s in specs.items() if s.reads] == ["watches"]
            properties = properties_of(specs["watch"])
            assert properties["kind"] == {"type": "string", "enum": ["claude_session"]}
            assert "tools" not in properties
    run(go())


def test_the_until_schema_enumerates_the_tracked_fields_and_bounds_nothing_nested(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            [watch, *_] = (await w.tools().catalogue()).specs
            text = json.dumps(watch.parameters)
            assert '"enum": ["seq", "status"]' in text and "maxItems" not in text
            assert properties_of(watch)["hours"]["maximum"] == 168
    run(go())


def test_a_watch_naming_a_tool_that_only_looks_is_armed_at_once_with_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            body(await call(w.tools(turn=(1, 5)), "watch", {"kind": "claude_session", "target": "s1", "tools": ["look"]}))
            [row] = stored(w)
            assert row["tools"] == ["look"]
            refused = await call(w.tools(turn=(1, 5)), "watch", {"kind": "claude_session", "target": "s2",
                                                                   "tools": ["delete_everything"]})
            assert refused.is_error and refused.content.startswith("bad_arguments") and len(stored(w)) == 1
    run(go())


def test_a_watch_that_acts_is_proposed_and_armed_only_by_arm_reminder_in_a_later_turn(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            args: dict[str, object] = {"kind": "claude_session", "target": "s1", "tools": ["switch"],
                                       "until": [[{"kind": "gone"}]], "hours": 5}
            made = body(await call(w.tools(turn=(1, 5)), "watch", args))
            assert made["armed"] is False and made["label"] == "build" and stored(w) == []
            reminders = ReminderTools(w.home, w.alana, private=True, turn=(1, 5))
            same = await call(reminders, "arm_reminder", {})
            assert same.is_error and same.content.startswith("same_turn") and stored(w) == []
            later = ReminderTools(w.home, w.alana, private=True, turn=(1, 6))
            armed = body(await call(later, "arm_reminder", {}))
            assert armed["armed"] is True and armed["label"] == "build"
            [row] = stored(w)
            assert (row["tools"], row["until_clauses"], row["armed_by"]) == (
                ["switch"], [[{"kind": "gone", "negate": False}]], "ashley")
            assert 4.9 * 3600 < scalar(db_url, "SELECT extract(epoch FROM expires_at - now()) FROM watches") <= 5 * 3600
            again = await call(later, "arm_reminder", {})
            assert again.is_error and again.content.startswith("none")
    run(go())


def test_a_proposed_watch_whose_session_has_gone_by_the_time_they_agree_is_refused_not_found(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await call(w.tools(turn=(1, 5)), "watch", {"kind": "claude_session", "target": "s1", "tools": ["switch"]})
            w.bridge.found = ()
            gone = await call(ReminderTools(w.home, w.alana, private=True, turn=(1, 6)), "arm_reminder", {})
            assert gone.is_error and gone.content.startswith("not_found") and stored(w) == []
    run(go())


def test_the_watch_proposal_survives_its_stored_form() -> None:
    r = Reminder(1, 2, 2, "build", datetime.now(UTC) + timedelta(days=1), None, tools=("switch",))
    for until in (None, ((ItemPredicate("gone"),),)):
        schedule = WatchSchedule(r, "claude_session", "s1", until, 5.0, 9)
        topic, stored_form = encode(schedule)
        assert topic == REMINDERS.name and REMINDERS.decode(json.loads(json.dumps(stored_form))) == schedule
    check(WatchSchedule(r, "claude_session", "s1", None, None, None))
    with pytest.raises(ValueError):
        check(WatchSchedule(replace(r, brief=""), "claude_session", "s1", None, None, None))


def inbound(**fields: Any) -> Inbound:
    base = Inbound(household_id=1, thread="person:1:web", text="hi", kind="chat", medium="text", audience="owner",
                   speaker_id=2, shared=False, place=None, channel="web", later=True, later_by="turn")
    return replace(base, **fields)


def test_a_turn_offers_the_watch_tools_only_where_the_reply_reaches_the_speaker_alone(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            own = replace(inbound(), household_id=w.home, speaker_id=w.alana)
            offered = {s.name for s in (await turn_tools.for_turn(own, (1, 5)).catalogue()).specs}
            assert {"watch", "unwatch", "watches"} <= offered
            shared = replace(own, audience="household", shared=True)
            there = {s.name for s in (await turn_tools.for_turn(shared, (1, 5)).catalogue()).specs}
            assert not {"watch", "unwatch", "watches"} & there
            nobody = replace(own, speaker_id=None)
            nothing = {s.name for s in (await turn_tools.for_turn(nobody, (1, 5)).catalogue()).specs}
            assert not {"watch", "unwatch", "watches"} & nothing
    run(go())


def test_no_log_line_carries_a_target_label_or_condition_value(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    async def go() -> None:
        async with world(db_url, sessions=(Session("secret-target-id", "secret-label", "/d", "done", 1, None),)) as w:
            args: dict[str, object] = {"kind": "claude_session", "target": "secret-target-id",
                                       "until": [[{"kind": "contains", "field": "status", "text": "secret-text"}]]}
            body(await call(w.tools(), "watch", args))
            await call(w.tools(), "watches", {})
            await call(w.tools(), "unwatch", {"kind": "claude_session", "target": "secret-target-id"})
    run(go())
    text = "\n".join(Logfmt().format(r) for r in caplog.records)
    assert "event=tools.call" in text and "event=watches.armed" in text
    assert not {"secret-target-id", "secret-label", "secret-text"} & set(text.replace("=", " ").split())
    assert "secret" not in text
