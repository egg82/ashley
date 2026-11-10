"""Where WatchTools are offered: only where the reply reaches the speaker alone, and only to a person who connected a
source some kind reads."""

import asyncio

import pytest
from watch_tools_blind_fakes import HOUSE, KIND, SAM, SPEC_NAMES, FakeKind
from watch_tools_blind_support import (
    body,
    inbound,
    offered,
    plain,
    refused,
    schema_of,
    source_keys,
    use,
    world,
)

from ashley.tools.tools import ToolsUnavailable


def test_the_three_tools_are_offered_to_a_person_who_connected_a_bridge() -> None:
    async def go() -> None:
        async with world() as w:
            assert sorted(await offered(w.tools())) == sorted(SPEC_NAMES)
    asyncio.run(go())


def test_nothing_is_offered_to_a_person_with_no_bridge() -> None:
    async def go() -> None:
        async with world(connected=False) as w:
            assert await offered(w.tools()) == []
    asyncio.run(go())


def test_nothing_is_offered_to_another_person_of_the_household() -> None:
    async def go() -> None:
        async with world() as w:
            assert await offered(w.tools(speaker=SAM)) == []
    asyncio.run(go())


def test_a_call_without_a_bridge_is_refused_and_arms_nothing() -> None:
    async def go() -> None:
        async with world(connected=False) as w:
            refused(await use(w.tools(), "watch", plain()))
            assert w.store.armed == [] and w.kind.reads == 0
    asyncio.run(go())


def test_connections_out_of_reach_is_tools_unavailable_not_an_empty_offer() -> None:
    async def go() -> None:
        async with world() as w:
            w.connections.down = True
            with pytest.raises(ToolsUnavailable):
                await w.tools().catalogue()
    asyncio.run(go())


def test_the_kind_enum_holds_only_kinds_this_person_can_use() -> None:
    async def go() -> None:
        async with world(extra=(FakeKind(name="calendar", port="ledger"),)) as w:
            spec = next(s for s in (await w.tools().catalogue()).specs if s.name == "watch")
            assert schema_of(spec)["properties"]["kind"]["enum"] == [KIND]
            w.connections.connect(HOUSE, "https://sure.example", "k", "sure", None)
            spec = next(s for s in (await w.tools().catalogue()).specs if s.name == "watch")
            assert sorted(schema_of(spec)["properties"]["kind"]["enum"]) == ["calendar", KIND]
    asyncio.run(go())


def test_a_kind_this_person_cannot_use_is_refused_even_if_named() -> None:
    async def go() -> None:
        async with world(extra=(FakeKind(name="calendar", port="ledger"),)) as w:
            refused(await use(w.tools(), "watch", {"kind": "calendar", "target": "x"}))
            assert w.store.armed == []
    asyncio.run(go())


def test_the_turn_offers_them_where_the_reply_reaches_the_speaker_alone() -> None:
    async def go() -> None:
        async with world():
            assert "watches" in source_keys(inbound())
            assert "watches" in source_keys(inbound(thread="bench:4", kind="brainstorm", bench_id=4))
    asyncio.run(go())


@pytest.mark.parametrize("fields", [
    {"audience": "household", "shared": True}, {"shared": True}, {"audience": "household"}, {"device_id": 3},
    {"speaker_id": None}])
def test_the_turn_does_not_offer_them_where_others_may_read_the_reply(fields: dict[str, object]) -> None:
    async def go() -> None:
        async with world():
            assert "watches" not in source_keys(inbound(**fields))
    asyncio.run(go())


def test_without_a_bridge_unwatch_is_refused_and_watches_answers_the_live_list() -> None:
    async def go() -> None:
        async with world(connected=False) as w:
            refused(await use(w.tools(), "unwatch", plain()))
            assert w.store.disarmed == []
            assert body(await use(w.tools(), "watches"))["watches"] == []
            assert len(w.store.lives) == 1
    asyncio.run(go())


def test_an_unknown_tool_name_is_an_error_result() -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch_everything", plain()), "unknown_tool")
    asyncio.run(go())


def test_the_listing_changes_nothing_and_says_so() -> None:
    async def go() -> None:
        async with world() as w:
            specs = {s.name: s for s in (await w.tools().catalogue()).specs}
            assert specs["watches"].reads is True
    asyncio.run(go())
