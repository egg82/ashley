"""Directed tests for the planted mutants the blind suite as first written let through (MUTANTS.txt)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from watch_tools_blind_fakes import KIND, FakeWatch
from watch_tools_blind_support import plain, refused, schema_of, use, world


@pytest.mark.parametrize("bad", ["5", True, False, [5], {"h": 5}])
def test_wtl_hours_that_are_not_numbers_are_refused(bad: Any) -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch", plain(hours=bad)), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())


def test_wtl_no_array_in_the_until_schema_carries_a_size_bound() -> None:
    async def go() -> None:
        async with world() as w:
            spec = next(s for s in (await w.tools().catalogue()).specs if s.name == "watch")
            assert "maxItems" not in json.dumps(schema_of(spec)["properties"]["until"])
    asyncio.run(go())


def test_wtl_an_armed_row_of_the_listing_carries_no_pause_field_at_all() -> None:
    async def go() -> None:
        async with world() as w:
            soon, later = datetime.now(UTC) + timedelta(hours=3), datetime.now(UTC) + timedelta(hours=30)
            w.store.rows = [FakeWatch(KIND, "a", "ay", (), soon, state="paused", reason="unreachable", id=1),
                            FakeWatch(KIND, "b", "bee", (), later, id=2)]
            paused, armed = json.loads((await use(w.tools(), "watches")).content)["watches"]
            assert set(armed) < set(paused) and len(set(paused) - set(armed)) == 1
    asyncio.run(go())


@pytest.mark.parametrize("clause", [
    [[{"kind": "equals", "field": "status", "value": None}]],
    [[{"kind": "one_of", "field": "status", "values": None}]],
    [[{"kind": "contains", "field": "status", "text": None}]]])
def test_wtl_a_predicate_with_a_null_where_its_kind_needs_a_value_is_refused(clause: Any) -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch", plain(until=clause)), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())
