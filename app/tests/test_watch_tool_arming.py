"""Her `watch` tool for the `tool` kind: she names a read, arms it with her fields and `until`, and the watch is stored
with that read as its baseline; and the read behind it is only ever one of the person's tools that reads."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ashley import services
from ashley.channels.watch_reads import ChannelToolReads
from ashley.connections.connections import Connections
from ashley.criteria import condition
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.proposal_payloads import REMINDERS, WatchSchedule, encode
from ashley.senses.wakes import Reminder
from ashley.tools import house_act
from ashley.tools.tools import Catalogue, Tools
from ashley.tools.watches import WatchTools
from ashley.watches.config import CONFIG
from ashley.watches.model import Arm, Armed, ReadFailed
from ashley.watches.tool_reads import Text, ToolRead, ToolReads
from ashley.watches.tool_target import parse, target_of
from ashley.watches.tool_watch import ToolWatch
from ashley.watches.watches import Watches
from money_support import HeldConnections
from test_reminder_turn import Home
from test_watches_tool import EVENTS, FakeReads, answer, event
from watch_job_support import FakeWatches

READ = {"tool": "house_ask", "arguments": {"action": "calendar.get_events", "ids": ["calendar.home"]},
        "path": ["response", "calendar.home", "events"], "track": ["summary", "start"]}
HOME = Household(1, "home", "America/Denver", "", (Person(7, 1, "Alana"),))


@dataclass
class Arming(FakeWatches):
    armed: list[Arm] = field(default_factory=list[Arm])

    async def arm(self, arm: Arm) -> Armed:
        self.armed.append(arm)
        return Armed(len(self.armed), True)


def call(reads: FakeReads, **args: object) -> tuple[ToolResult, Arming]:
    store = Arming()
    services.register(Watches, store)
    services.register(ToolReads, reads)
    services.register(People, Home(HOME))
    services.register(Connections, HeldConnections())
    try:
        return asyncio.run(WatchTools(1, 7).call(ToolCall("c1", "watch", {"kind": "tool", **args}))), store
    finally:
        for interface in (Watches, ToolReads, People, Connections):
            services.unregister(interface)


def test_she_arms_a_read_with_her_fields_and_the_read_now_is_the_baseline() -> None:
    reads = FakeReads([Text(answer(event("Dentist")))])
    result, store = call(reads, read=READ, until=[[{"kind": "gone"}]])
    assert not result.is_error
    arm = store.armed[0]
    assert (arm.kind, arm.track, arm.person_id, arm.armed_by) == ("tool", ("summary", "start"), 7, "ashley")
    assert parse(arm.target) == EVENTS and arm.label == "house_ask calendar.get_events"
    assert arm.baseline == {"Dentist": {"summary": "Dentist", "start": "2026-11-20T09:00"}}
    assert condition.to_json(arm.until or ()) == [[{"kind": "gone", "negate": False}]]
    assert condition.to_json(arm.when) == condition.to_json(CONFIG.kinds["tool"].when)
    assert arm.expires_at - datetime.now(UTC) < timedelta(hours=CONFIG.kinds["tool"].hours, seconds=5)
    assert reads.calls == [(1, 7, "house_ask", EVENTS.arguments)]


def test_a_when_of_hers_replaces_the_default_and_reads_her_tracked_fields() -> None:
    when = [[{"kind": "new"}], [{"kind": "contains", "field": "summary", "text": "dentist"}]]
    _, store = call(FakeReads([Text(answer())]), read=READ, when=when)
    assert len(store.armed[0].when) == 2 and store.armed[0].when[1][0].field == "summary"
    assert store.armed[0].baseline == {}


def test_without_a_path_the_whole_answer_is_the_one_item_tracked_as_a_hash() -> None:
    _, store = call(FakeReads([Text('{"items":[]}')]), read={"tool": "house_ask", "arguments": {"action": "todo.get_items"}})
    assert store.armed[0].track == ("hash",) and list(store.armed[0].baseline or {}) == ["result"]


def test_a_field_she_does_not_track_is_refused_in_until_and_when() -> None:
    for where in ("until", "when"):
        result, store = call(FakeReads([Text(answer())]), read=READ, **{where: [[{"kind": "changed", "field": "location"}]]})
        assert result.is_error and result.content.startswith("bad_arguments") and store.armed == []


def test_read_is_for_the_tool_kind_only_and_the_tool_kind_takes_nothing_else() -> None:
    store = Arming()
    services.register(Watches, store)
    services.register(ToolReads, FakeReads([Text("{}")]))
    services.register(People, Home(HOME))
    services.register(Connections, HeldConnections())
    try:
        tools = WatchTools(1, 7)
        other = asyncio.run(tools.call(ToolCall("c", "watch", {"kind": "tool", "target": "x", "read": READ})))
        assert other.is_error and other.content.startswith("bad_arguments")
        bare = asyncio.run(tools.call(ToolCall("c", "watch", {"kind": "tool"})))
        assert bare.is_error and bare.content.startswith("bad_arguments")
    finally:
        for interface in (Watches, ToolReads, People, Connections):
            services.unregister(interface)
    assert store.armed == []


def test_a_read_that_fails_arms_nothing_and_says_why() -> None:
    result, store = call(FakeReads([ReadFailed("refused")]), read=READ)
    assert result.is_error and result.content.startswith("refused") and store.armed == []


def test_the_result_of_arming_is_outside_text_and_shows_what_was_read() -> None:
    result, _ = call(FakeReads([Text(answer(event("Dentist")))]), read=READ)
    body = json.loads(result.content)
    assert result.outside is True and body["now"] == {"Dentist": {"summary": "Dentist", "start": "2026-11-20T09:00"}}


def test_a_read_too_long_for_a_target_is_refused_naming_the_limit() -> None:
    result, store = call(FakeReads([Text(answer())]), read={**READ, "arguments": {"data": "x" * 600}})
    assert result.is_error and "500" in result.content and store.armed == []


LOOK = ToolSpec("look", "see something", {"type": "object"}, reads=True)
SWITCH = ToolSpec("switch", "turn something on", {"type": "object"}, reads=False)


@dataclass
class Board(Tools):
    ran: list[str] = field(default_factory=list[str])

    async def catalogue(self) -> Catalogue:
        return Catalogue((LOOK, SWITCH), "")

    async def call(self, call: ToolCall) -> ToolResult:
        self.ran.append(call.name)
        return ToolResult(call.id, f'{{"ran":"{call.name}"}}')


def read_through(board: Board, tool: str) -> ToolRead:
    services.register(Tools, board)
    try:
        return asyncio.run(ChannelToolReads().read(1, 7, tool, {}))
    finally:
        services.unregister(Tools)


def test_a_tool_that_changes_things_is_never_run_for_a_watch_and_one_that_reads_is() -> None:
    board = Board()
    assert read_through(board, "switch") == ReadFailed("refused") and board.ran == []
    assert read_through(board, "no_such_tool") == ReadFailed("refused") and board.ran == []
    assert read_through(board, "look") == Text('{"ran":"look"}') and board.ran == ["look"]


def test_house_ask_says_it_reads_and_house_do_does_not() -> None:
    assert house_act.ASK_SPEC.reads and not house_act.DO_SPEC.reads


def test_an_answer_that_is_an_error_is_a_bad_result_not_an_empty_one() -> None:
    @dataclass
    class Failing(Board):
        async def call(self, call: ToolCall) -> ToolResult:
            return ToolResult(call.id, "nothing matches", is_error=True)

    assert read_through(Failing(), "look") == ReadFailed("bad_result")


def test_a_target_the_kind_lists_is_offered_only_where_a_tool_can_be_read() -> None:
    assert asyncio.run(ToolWatch().available(1, 7)) is False
    services.register(ToolReads, FakeReads([Text("{}")]))
    try:
        assert asyncio.run(ToolWatch().available(1, 7)) is True
    finally:
        services.unregister(ToolReads)



def test_the_watch_tool_offers_read_and_when_and_drops_the_target_requirement_only_where_the_tool_kind_is_usable() -> None:
    services.register(Connections, HeldConnections())
    services.register(People, Home(HOME))
    try:
        bare = {s.name: s for s in asyncio.run(WatchTools(1, 7).catalogue()).specs}
        services.register(ToolReads, FakeReads([Text("{}")]))
        full = {s.name: s for s in asyncio.run(WatchTools(1, 7).catalogue()).specs}
    finally:
        for interface in (ToolReads, People, Connections):
            services.unregister(interface)
    assert "watch" not in bare
    schema: dict[str, Any] = dict(full["watch"].parameters)
    assert {"read", "when"} <= set(schema["properties"]) and schema["required"] == ["kind"]


def test_a_proposed_tool_watch_keeps_its_when_through_storage() -> None:
    reminder = Reminder(1, 7, 7, "x", datetime.now(UTC), None)
    when = condition.from_json([[{"kind": "new", "negate": False}]])
    schedule = WatchSchedule(reminder, "tool", target_of(EVENTS), None, None, None, None, False, when)
    topic, stored = encode(schedule)
    again = REMINDERS.decode(json.loads(json.dumps(stored)))
    assert topic == REMINDERS.name and isinstance(again, WatchSchedule) and again.when == when
    assert encode(WatchSchedule(reminder, "tool", "t", None, None, None, None, False))[1]["when"] is None
