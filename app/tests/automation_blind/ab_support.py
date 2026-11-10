"""Support for the blind automation-install tests: one household of two people (and one stranger), the real Postgres
Workshop and Installs over the fake Home Assistant, a wrapper that shows what the Installs record said at each write to
the house, and builders for the commands a bench sees."""

import json
from collections.abc import AsyncGenerator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from itertools import count
from typing import Any

from ashley import services
from ashley.home_assistant.automations import Automation, Automations
from ashley.inference.model import ToolCall
from ashley.tools.bench_automations import BenchAutomationTools
from ashley.workshop.commands import Add, Edit, Install, Propose, Undo
from ashley.workshop.install_piece import automation_id_for, carry_out
from ashley.workshop.installs import InstallRecord, Installs
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.workshop import Applied, Workshop
from automations_support import FakeHouse
from contract.conversations_support import household, person
from install_support import CONFIG as CONFIG, World, body as body, world as base_world

@dataclass(frozen=True)
class Crowd:
    """Alana and Sam share a household; Zed lives in another."""

    alana: Owner
    sam: Owner
    zed: Owner


def people(url: str) -> Crowd:
    h1, h2 = household(url, "home"), household(url, "next door")
    return Crowd(Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")),
                 Owner(h2, person(url, h2, "Zed")))


class Seen(Automations):
    """Wraps the fake house: before each write (config write, delete, turn on or off) it notes whether the Installs
    record of every install it was told about already existed and had not yet ended."""

    def __init__(self, inner: Automations) -> None:
        self.inner = inner
        self.watch: list[tuple[int, int, int]] = []
        """(household_id, bench_id, seq) of installs to look for."""
        self.at_writes: list[tuple[str, list[bool]]] = []
        """For each write, its name and for each watched install whether a record without an ending stood."""

    async def _note(self, what: str) -> None:
        stood: list[bool] = []
        for h, b, s in self.watch:
            record = await services.get(Installs).of(h, b, s)
            stood.append(record is not None and record.ending is None)
        self.at_writes.append((what, stood))

    def offered(self) -> bool:
        return self.inner.offered()

    async def listed(self) -> list[Automation]:
        return await self.inner.listed()

    async def config(self, automation_id: str) -> dict[str, Any] | None:
        return await self.inner.config(automation_id)

    async def write(self, automation_id: str, config: Mapping[str, Any]) -> str | None:
        await self._note("write")
        return await self.inner.write(automation_id, config)

    async def delete(self, automation_id: str) -> bool:
        await self._note("delete")
        return await self.inner.delete(automation_id)

    async def set_enabled(self, entity_id: str, enabled: bool) -> None:
        await self._note("set_enabled")
        await self.inner.set_enabled(entity_id, enabled)


@asynccontextmanager
async def crowd(url: str, house: FakeHouse | None = None) -> AsyncGenerator[tuple[World, Crowd]]:
    async with base_world(url, house) as w:
        yield w, people(url)


def add(owner: Owner, text: str | None = None, kind: str = "automation") -> Add:
    return Add(By(owner.person_id), kind, Text("porch", body() if text is None else text), "medium")


def edit(owner: Owner, piece: int, version: int, **changes: object) -> Edit:
    return Edit(By(owner.person_id), piece, version, Text("porch", body(**changes)))


def edit_text(owner: Owner, piece: int, text: str, version: int = 1) -> Edit:
    return Edit(By(owner.person_id), piece, version, Text("porch", text))


def propose(piece: int, version: int, enabled: bool = False, turn_off: str | None = None, by: By = HER) -> Propose:
    return Propose(by, piece, version, enabled, turn_off)


def install(owner: Owner, bench_id: int, proposal: int, piece: int, by: By | None = None) -> Install:
    return Install(by or By(owner.person_id), piece, proposal, automation_id_for(bench_id, piece))


def undo(owner: Owner, seq: int, by: By | None = None) -> Undo:
    return Undo(by or By(owner.person_id), seq)


async def bench_with_piece(owner: Owner, text: str | None = None, kind: str = "automation") -> tuple[int, int]:
    """(bench id, piece id) of a new bench holding one piece."""
    shop = services.get(Workshop)
    bench = (await shop.open(owner, "desk")).id
    applied = await shop.apply(owner, bench, add(owner, text, kind))
    assert applied.piece_id is not None
    return bench, applied.piece_id


async def carried(owner: Owner, bench: int, command: Install | Undo | Propose | Edit | Add) -> tuple[Applied, InstallRecord | None]:
    """Apply `command` as the route does and carry it out."""
    applied = await services.get(Workshop).apply(owner, bench, command)
    return applied, await carry_out(owner, bench, applied)


async def installed(owner: Owner, bench: int, piece: int, version: int = 1, enabled: bool = False,
                    turn_off: str | None = None) -> tuple[int, int, InstallRecord | None]:
    """Her proposal then the person's Install, carried out: (proposal seq, install seq, record)."""
    proposed = await services.get(Workshop).apply(owner, bench, propose(piece, version, enabled, turn_off))
    assert proposed.outcome == "accepted", proposed.outcome
    applied, record = await carried(owner, bench, install(owner, bench, proposed.seq, piece))
    assert applied.outcome == "accepted", applied.outcome
    return proposed.seq, applied.seq, record


_ids = count(1)


def tool_call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(f"call-{next(_ids)}", name, arguments)


def parsed(content: str) -> object:
    return json.loads(content)


def objects(node: object) -> Iterator[dict[str, object]]:
    """Every JSON object in a tool result, however deep."""
    loose: Any = node
    if isinstance(node, dict):
        found = {str(k): v for k, v in dict[object, object](loose).items()}
        yield found
        for v in found.values():
            yield from objects(v)
    elif isinstance(node, list):
        for v in list[object](loose):
            yield from objects(v)


def tools_for(owner: Owner, bench: int) -> BenchAutomationTools:
    return BenchAutomationTools(owner.household_id, owner.person_id, bench)
