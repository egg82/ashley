"""`watch`'s `until`: the clause shape, its fields enumerated from the kind's track, handed to the store as
`ItemPredicate` alternatives; anything else is refused, never guessed, and nothing is armed."""

import asyncio
from typing import Any

import pytest
from watch_tools_blind_fakes import FakeKind
from watch_tools_blind_support import (
    body,
    plain,
    predicate,
    refused,
    schema_of,
    use,
    world,
)

from ashley.criteria.items import ItemPredicate

DONE = predicate("equals", field="status", value="done")
GONE = predicate("gone")


def test_until_reaches_the_store_as_alternatives_of_item_predicates() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(until=[[DONE], [GONE]])))
            (arm,) = w.store.armed
            assert arm.until == ((ItemPredicate("equals", field="status", value="done"),), (ItemPredicate("gone"),))
    asyncio.run(go())


def test_the_predicates_of_one_alternative_stay_together() -> None:
    async def go() -> None:
        async with world() as w:
            both = [DONE, predicate("changed", field="seq")]
            body(await use(w.tools(), "watch", plain(until=[both])))
            (arm,) = w.store.armed
            assert len(arm.until) == 1 and len(arm.until[0]) == 2
    asyncio.run(go())


def test_not_negates_a_predicate() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(until=[[{**DONE, "not": True}]])))
            assert w.store.armed[0].until == ((ItemPredicate("equals", True, "status", "done"),),)
    asyncio.run(go())


def test_of_before_reads_the_side_before() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(until=[[{**DONE, "of": "before"}]])))
            assert w.store.armed[0].until[0][0].of == "before"
            refused(await use(w.tools(), "watch", plain(until=[[{**DONE, "of": "sideways"}]])), "bad_arguments")
    asyncio.run(go())


@pytest.mark.parametrize("clause", [
    predicate("one_of", field="status", values=["done", "blocked"]),
    predicate("number", field="seq", min=3), predicate("number", field="seq", max=9),
    predicate("number", field="seq", min=1, max=9), predicate("contains", field="status", text="DON"),
    predicate("new"), predicate("changed", field="status")])
def test_every_kind_of_predicate_the_clause_shape_has_is_accepted(clause: dict[str, Any]) -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(until=[[clause]])))
            assert len(w.store.armed) == 1
    asyncio.run(go())


def test_a_field_outside_the_kinds_track_is_refused() -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch", plain(until=[[predicate("equals", field="label", value="x")]])),
                    "bad_arguments")
            refused(await use(w.tools(), "watch", plain(until=[[predicate("changed", field="dir")]])), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())


def test_the_track_is_the_kinds_own() -> None:
    async def go() -> None:
        async with world(extra=(FakeKind(name="calendar", port="herdr", track=("start", "title")),)) as w:
            body(await use(w.tools(), "watch", {"kind": "calendar", "target": "sess-wtl-1",
                                                "until": [[predicate("changed", field="start")]]}))
            refused(await use(w.tools(), "watch", {"kind": "calendar", "target": "sess-wtl-1",
                                                   "until": [[predicate("changed", field="status")]]}), "bad_arguments")
    asyncio.run(go())


def test_the_until_fields_are_enumerated_from_the_track_in_the_schema() -> None:
    async def go() -> None:
        async with world() as w:
            spec = next(s for s in (await w.tools().catalogue()).specs if s.name == "watch")
            until: Any = schema_of(spec)["properties"]["until"]
            assert until["type"] == "array" and until["items"]["type"] == "array"
            assert until["items"]["items"]["properties"]["field"]["enum"] == sorted(["status", "seq"])
    asyncio.run(go())


NOT_ALTERNATIVES: list[Any] = [
    "done", {"kind": "gone"}, [GONE], [[]], [[{}]], [[{"kind": "bogus"}]], [[{"field": "status"}]], [["gone"]], [[[GONE]]],
    [[DONE], []], 5, True]


@pytest.mark.parametrize("bad", NOT_ALTERNATIVES)
def test_a_clause_that_is_not_alternatives_of_predicates_is_refused(bad: Any) -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch", plain(until=bad)), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())


@pytest.mark.parametrize("bad", [
    predicate("equals", field="status"), predicate("equals", field="status", value=None),
    predicate("equals", value="done"), predicate("one_of", field="status"), predicate("one_of", field="status", values="done"),
    predicate("number", field="seq"), predicate("contains", field="status", text=""),
    predicate("contains", field="status", text="x" * 201), predicate("contains", field="status"),
    predicate("changed"), predicate("gone", field="status"), predicate("new", value=1),
    predicate("equals", field="status", value=["done"])])
def test_a_predicate_missing_what_its_kind_needs_or_carrying_what_it_cannot_is_refused(bad: dict[str, Any]) -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch", plain(until=[[bad]])), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())


def test_a_contains_text_of_two_hundred_characters_is_accepted() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(until=[[predicate("contains", field="status", text="x" * 200)]])))
    asyncio.run(go())


def test_a_condition_over_the_stores_limits_is_an_error_result() -> None:
    async def go() -> None:
        async with world() as w:
            w.store.arm_raises = ValueError("a condition has at most 4 alternatives")
            refused(await use(w.tools(), "watch", plain(until=[[DONE]])), "bad_arguments")
    asyncio.run(go())


def test_leaving_until_out_arms_a_watch_that_only_expires() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain()))
            assert w.store.armed[0].until == ()
    asyncio.run(go())


def test_there_is_no_when_argument() -> None:
    async def go() -> None:
        async with world() as w:
            spec = next(s for s in (await w.tools().catalogue()).specs if s.name == "watch")
            assert sorted(schema_of(spec)["properties"]) == [
                "brief", "hours", "kind", "standing", "target", "tools", "until"]
            assert sorted(schema_of(spec)["required"]) == ["kind", "target"]
    asyncio.run(go())
