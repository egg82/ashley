"""The schemas every provider adapter accepts (flat arrays), and the rule that arguments and results are never
logged."""

import asyncio
import logging
from typing import Any

import pytest
from provider_schema_support import WIRES, collect, violations
from watch_tools_blind_fakes import PLANT, SPEC_NAMES, TARGET
from watch_tools_blind_support import (
    body,
    logline,
    plain,
    predicate,
    refused,
    schema_of,
    use,
    world,
)

from ashley.inference.model import ToolSpec


async def specs() -> list[ToolSpec]:
    async with world() as w:
        return list((await w.tools().catalogue()).specs)


@pytest.mark.parametrize("provider", sorted(WIRES))
def test_no_watch_tool_schema_carries_a_keyword_a_provider_rejects(provider: str) -> None:
    mine = asyncio.run(specs())
    assert sorted(s.name for s in mine) == sorted(SPEC_NAMES)
    assert violations(provider, collect(provider, mine)) == []


def test_the_probe_can_fail_on_the_nested_maxitems_gemini_rejects() -> None:
    nested = {"type": "array", "maxItems": 2, "items": {"type": "array", "maxItems": 2, "items": {"type": "string"}}}
    planted = ToolSpec("watch_planted", "x", {"type": "object", "properties": {"until": nested}})
    assert violations("gemini", collect("gemini", [planted])) != []


def test_until_is_a_flat_array_of_arrays_with_no_bounds_on_the_nested_array() -> None:
    async def go() -> None:
        until: Any = schema_of(next(s for s in await specs() if s.name == "watch"))["properties"]["until"]
        assert until["type"] == "array" and until["items"]["type"] == "array"
        assert "maxItems" not in until or "maxItems" not in until["items"]
        assert until["items"]["items"]["type"] == "object"
    asyncio.run(go())


def test_watch_requires_kind_and_target_and_bounds_hours_from_one() -> None:
    async def go() -> None:
        spec: Any = next(s for s in await specs() if s.name == "watch")
        props = schema_of(spec)["properties"]
        assert schema_of(spec)["required"] == ["kind", "target"] or sorted(schema_of(spec)["required"]) == ["kind", "target"]
        assert props["hours"]["type"] == "number" and props["hours"]["minimum"] == 1
        assert props["tools"]["type"] == "array" and props["tools"]["items"] == {"type": "string"}
        assert props["target"]["type"] == "string"
    asyncio.run(go())


def test_unwatch_requires_kind_and_target_and_watches_none() -> None:
    async def go() -> None:
        by: Any = {s.name: s for s in await specs()}
        assert sorted(schema_of(by["unwatch"])["required"]) == ["kind", "target"]
        assert not schema_of(by["watches"]).get("properties")
    asyncio.run(go())


def test_nothing_a_call_carries_or_returns_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        async with world() as w:
            with caplog.at_level(logging.DEBUG):
                body(await use(w.tools(), "watch", plain(until=[[predicate("contains", field="status", text=PLANT)]])))
                body(await use(w.tools(), "watches"))
                body(await use(w.tools(), "unwatch", plain()))
                refused(await use(w.tools(), "watch", plain(until=[[predicate("equals", field=PLANT, value=PLANT)]])))
                refused(await use(w.tools(), "watch", {"kind": PLANT, "target": PLANT}))
    asyncio.run(go())
    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert PLANT not in logged and TARGET not in logged and "WTL-PLANTED" not in logged


def test_the_result_text_is_not_logged_either(caplog: pytest.LogCaptureFixture) -> None:
    from watch_tools_blind_fakes import LABEL

    async def go() -> None:
        async with world() as w:
            with caplog.at_level(logging.DEBUG):
                body(await use(w.tools(), "watch", plain()))
    asyncio.run(go())
    assert LABEL not in "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)


def test_a_call_leaves_a_tools_call_line_with_the_tool_and_outcome(caplog: pytest.LogCaptureFixture) -> None:
    async def go() -> None:
        async with world() as w:
            with caplog.at_level(logging.INFO):
                body(await use(w.tools(), "watches"))
    asyncio.run(go())
    lines = [logline(r) for r in caplog.records if "tools.call" in logline(r)]
    assert lines and "watches" in lines[0] and "ok" in lines[0]
