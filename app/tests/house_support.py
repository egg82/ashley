"""Helpers for `house_state`'s tests: a house written as a list of devices (`device`: names and area each a name then its
aliases joined by ", ", `areas` and `attributes` left out when there are none), held by an in-memory House, and a crawler
that follows the tool's answers down every level."""

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from ashley.home_assistant.house import State
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.house_entities import Entity
from ashley.tools.house_state import HouseStateTools
from ashley.tools.house_state_config import HouseStateConfig
from ashley.tools.house_targets import entity_of
from house_double_support import MemoryHouse, state


@dataclass(frozen=True)
class Device:
    names: str
    domain: str
    value: str
    areas: str
    attributes: Mapping[str, object]


def device(names: str, domain: str, value: str, area: str | None = None, **attributes: object) -> Device:
    return Device(names, domain, value, area or "", attributes)


def house_of(devices: list[Device]) -> MemoryHouse:
    """The devices as a House: each one's first name its name, the rest aliases; its area likewise."""
    things: list[State] = []
    for i, d in enumerate(devices):
        names = [n.strip() for n in d.names.split(", ") if n.strip()] or [f"{d.domain} {i}"]
        areas = [a.strip() for a in d.areas.split(", ") if a.strip()]
        listed = state(f"{d.domain}.d{i}", names[0], d.value, areas[0] if areas else None, tuple(names[1:]), tuple(areas[1:]))
        things.append(replace(listed, attributes=d.attributes))
    return MemoryHouse(things=things)


def entities_of(devices: list[Device]) -> tuple[Entity, ...]:
    return tuple(entity_of(s) for s in house_of(devices).things)


def tools(devices: list[Device], config: HouseStateConfig) -> tuple[HouseStateTools, MemoryHouse]:
    house = house_of(devices)
    return HouseStateTools(house, config), house


def ask(tools: HouseStateTools, **arguments: object) -> ToolResult:
    return asyncio.run(tools.call(ToolCall("c1", "house_state", arguments)))


def read(tools: HouseStateTools, **arguments: object) -> dict[str, Any]:
    result = ask(tools, **arguments)
    assert not result.is_error, result.content
    loaded: dict[str, Any] = json.loads(result.content)
    return loaded


Ask = Callable[..., dict[str, Any]]


@dataclass
class Crawl:
    """What a crawl reached: each entity as (names, domain, area, state), and every answer's size."""

    reached: set[tuple[str, str, str, str]] = field(default_factory=set[tuple[str, str, str, str]])
    sizes: list[int] = field(default_factory=list[int])


def crawl(ask_: Ask, depth: int = 6) -> Crawl:
    """Follow the answers from the house down: each area, each domain in it, and, where an entity list did not fit,
    the names or kinds it offered instead, as the tool's description tells her to."""
    seen = Crawl()
    _follow(ask_, {}, seen, depth)
    return seen


def _follow(ask_: Ask, arguments: Mapping[str, str], seen: Crawl, depth: int) -> None:
    body = ask_(**arguments)
    seen.sizes.append(len(json.dumps(body, separators=(",", ":"), ensure_ascii=False)))
    if depth == 0:
        return
    for nxt in _next(body, arguments):
        _follow(ask_, nxt, seen, depth - 1)
    for e in _list(body, "entities"):
        seen.reached.add((str(e["names"]), str(e["domain"]), str(e["area"]), str(e["state"])))


def _next(body: dict[str, Any], arguments: Mapping[str, str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for a in _list(body, "areas"):
        out.append({"area": str(a["area"])})
    for d in _list(body, "domains"):
        out.append({**arguments, "domain": str(d["domain"])})
    for g in _list(body, "groups"):
        where = {"area": str(g["area"]), "domain": str(g["domain"])}
        out.extend({**where, "name": str(n)} for n in g.get("names", []))
        if "names" not in g and "kind" in g:
            out.append({**where, "name": str(g["kind"])})
    return out


def _list(body: dict[str, Any], key: str) -> list[dict[str, Any]]:
    loose: Any = body.get(key)
    if not isinstance(body.get(key), list):
        return []
    items: list[Any] = list(loose)
    return [dict[str, Any](v) for v in items]
