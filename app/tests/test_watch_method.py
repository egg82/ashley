"""A watch can carry a standing errand's method. `watch` takes it as `remind` does (a kind of the household's work that has
a method, else refused naming the kinds), the store keeps it, a proposal carries it through storage,
and the turn its wake starts carries it (`Inbound.method`): the turn loads the skill beside its tools, says to do nothing
when the skill cannot be read, and is one turn however often the wake is handed in."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.channels.wake import watch_turn
from ashley.connections.connections import Connections
from ashley.db.pool import PoolDatabase
from ashley.herdr.model import Session
from ashley.inference.model import ToolCall
from ashley.people.people import People
from ashley.senses.proposal_payloads import REMINDERS, WatchSchedule, encode
from ashley.senses.wakes import Reminder, Wakes, WatchWake
from ashley.skills import config, seeds
from ashley.skills.postgres import PostgresSkills
from ashley.skills.skills import Skills
from ashley.tools.standing_method import UNREAD
from ashley.tools.watches import WatchTools
from ashley.watches.claude_session import NAME, items_of
from ashley.watches.config import CONFIG
from ashley.watches.model import Arm
from ashley.watches.tool_reads import ToolReads
from ashley.watches.watches import Watches
from bench_reacts_support import SAYS
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run, scalar
from money_support import HeldConnections
from test_reminder_turn import Home
from test_watch_tool_arming import HOME, READ, Arming, Text, answer, event
from test_watches_tool import FakeReads
from test_watch_wake_turn import turns_on
from watch_session_support import SESSION, Watching, watching

LOADED = "# Method for this standing errand (skill research"


@asynccontextmanager
async def skilled(url: str) -> AsyncGenerator[None]:
    """The real skills on `url`, whose seeds give every household a `research` method."""
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    loaded = config.load()
    services.register(Skills, PostgresSkills(db, loaded, seeds.load(loaded)))
    try:
        yield
    finally:
        services.unregister(Skills)
        await db.close()


async def armed_by_tool(**args: object) -> tuple[str, Arming]:
    """What `watch` answers for a read of hers with `args` added, and the store it armed into."""
    store = Arming()
    wired = ((Watches, store), (People, Home(HOME)), (Connections, HeldConnections()),
             (ToolReads, FakeReads([Text(answer(event("Dentist")))])))
    for interface, impl in wired:
        services.register(interface, impl)
    try:
        got = await WatchTools(1, 7).call(ToolCall("c1", "watch", {"kind": "tool", "read": READ, **args}))
        return got.content, store
    finally:
        for interface, _ in wired:
            services.unregister(interface)


def test_watch_with_a_method_arms_a_watch_that_carries_it(db_url: str) -> None:
    async def go() -> None:
        async with skilled(db_url):
            content, store = await armed_by_tool(method="research")
            assert [a.method for a in store.armed] == ["research"], content
            _, plain = await armed_by_tool()
            assert [a.method for a in plain.armed] == [None]

    run(go())


@pytest.mark.parametrize("method", ["nonesuch", "Not A Slug!", "", 3, ["research"]])
def test_a_method_naming_no_kind_with_a_method_is_refused_naming_the_kinds_and_nothing_is_armed(
        db_url: str, method: object) -> None:
    async def go() -> None:
        async with skilled(db_url):
            content, store = await armed_by_tool(method=method)
            assert content.startswith("bad_arguments") and "research" in content, content
            assert store.armed == []

    run(go())


async def arm_with(w: Watching, method: str | None, bench: int | None = None) -> int:
    kind = CONFIG.kinds[NAME]
    arm = Arm(w.home.home, w.person, NAME, SESSION, "label", bench, "ashley", kind.track, kind.when, None, None,
              kind.interval_s, datetime.now(UTC) + timedelta(hours=kind.handoff_hours),
              items_of(SESSION, Session(SESSION, "label", "dir", "working", 1000, None)), method=method)
    return (await services.get(Watches).arm(arm)).id


def stored_methods(w: Watching) -> list[object]:
    return list(scalar(w.db_url, "SELECT coalesce(json_agg(method ORDER BY id), '[]') FROM watches"))


def test_the_store_keeps_a_watchs_method_and_a_rearm_replaces_it(db_url: str) -> None:
    async def go() -> None:
        async with watching(db_url) as w:
            first = await arm_with(w, "research")
            assert stored_methods(w) == ["research"]
            (live,) = await services.get(Watches).live(w.home.home, w.person)
            assert live.method == "research"
            assert await arm_with(w, None) == first and stored_methods(w) == [None]

    run(go())


def test_a_proposed_watch_keeps_its_method_through_storage() -> None:
    reminder = Reminder(1, 7, 7, "x", datetime.now(UTC), None)
    schedule = WatchSchedule(reminder, "tool", "t", None, None, None, None, False, None, "research")
    topic, stored = encode(schedule)
    again = REMINDERS.decode(json.loads(json.dumps(stored)))
    assert topic == REMINDERS.name and isinstance(again, WatchSchedule) and again.method == "research"
    plain = REMINDERS.decode(json.loads(json.dumps(encode(WatchSchedule(reminder, "tool", "t", None, None, None, None,
                                                                         False))[1])))
    assert isinstance(plain, WatchSchedule) and plain.method is None


async def fire(w: Watching, method: str | None) -> tuple[int, WatchWake]:
    """The wake the session finishing stores for a watch with `method`."""
    await arm_with(w, method)
    await w.settle()
    w.bridge.state("done", 1002)
    await w.tick()
    [due] = await services.get(Wakes).due(10)
    assert isinstance(due.wake, WatchWake)
    return due.id, due.wake


def test_the_woken_turn_carries_the_method_and_loads_the_skill(db_url: str, connection_kinds_wired: None,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    turns: list[Inbound] = []

    async def seen(turn: Inbound) -> None:
        turns.append(turn)

    monkeypatch.setattr(watch_turn, "respond", seen)

    async def go() -> None:
        async with watching(db_url) as w, skilled(db_url):
            wake_id, wake = await fire(w, "research")
            assert await watch_turn.fired(wake_id, wake, 0.0) == "turn"
            [turn] = turns
            assert turn.method == "research" and turn.source == f"wake:{wake_id}"
            instructions = (await for_turn(turn).catalogue()).instructions or ""
            assert LOADED in instructions

    run(go())


def test_a_watch_without_a_method_loads_none(db_url: str, connection_kinds_wired: None,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    turns: list[Inbound] = []

    async def seen(turn: Inbound) -> None:
        turns.append(turn)

    monkeypatch.setattr(watch_turn, "respond", seen)

    async def go() -> None:
        async with watching(db_url) as w, skilled(db_url):
            wake_id, wake = await fire(w, None)
            await watch_turn.fired(wake_id, wake, 0.0)
            [turn] = turns
            assert turn.method is None
            assert LOADED not in ((await for_turn(turn).catalogue()).instructions or "")

    run(go())


def test_a_method_that_cannot_be_read_tells_her_to_carry_out_nothing(db_url: str, connection_kinds_wired: None,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    turns: list[Inbound] = []

    async def seen(turn: Inbound) -> None:
        turns.append(turn)

    monkeypatch.setattr(watch_turn, "respond", seen)

    async def go() -> None:
        async with watching(db_url) as w:
            services.unregister(Skills)
            wake_id, wake = await fire(w, "research")
            await watch_turn.fired(wake_id, wake, 0.0)
            assert UNREAD in ((await for_turn(turns[0]).catalogue()).instructions or "")

    run(go())


def test_a_wake_handed_in_twice_is_one_turn_with_the_method(db_url: str, connection_kinds_wired: None) -> None:
    async def go() -> None:
        async with watching(db_url) as w, skilled(db_url):
            w.home.model.script = [SAYS, SAYS]
            wake_id, wake = await fire(w, "research")
            assert await watch_turn.fired(wake_id, wake, 0.0) == "turn"
            assert await watch_turn.fired(wake_id, wake, 0.0) == "turn"
            thread = f"push:{w.person}"
            assert [s for _, _, s in turns_on(db_url, thread) if s == f"wake:{wake_id}"] == [f"wake:{wake_id}"]
            assert len(w.home.model.prompts) == 1

    run(go())
