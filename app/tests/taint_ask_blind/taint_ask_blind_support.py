"""Helpers for the blind tests of the tainted turn's wrapper (`decisions.md`, "A turn that has read outside words asks
before it does anything consequential the person did not ask for", second part): a migrated database with the real
proposals store, a scripted inner source that records which calls reach it, builders for the turn's `Inbound`, specs
and results, and the wrapper itself.

Every guess beyond the design is in ASSUMPTIONS below and only here; they are listed with the spec phrase each rests
on in `~/scratch/ashley/taint/taint-ask-blind/assumptions.txt`. Names part 1 of the item adds (`Inbound.taint`,
`ToolSpec.outside`, `ToolSpec.agrees`, `ToolResult.outside`, `Steps.tainted`) are used only in this file."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import psycopg
import pytest
from ashley import services
from ashley.channels.model import Audience, Inbound
from ashley.channels import standing
from ashley.channels.steps import NO_STEPS, Steps
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.senses.proposals import Proposal, Proposals
from ashley.tools.outside import CARRY_OUT, Outside
from ashley.tools.tools import Catalogue, Tools
from contract.conversations_support import household, person, scalar
from contract.conversations_support import run as run_bounded

# --- ASSUMPTIONS: every guess, change here only ----------------------------------------------------------------------
# A1  `Outside(source, inbound, turn, steps, tainted)` in `ashley.tools.outside`: `turn` is (conversation id, person
#     turn id) as `HouseChangeTools` takes it; `steps` defaults to `NO_STEPS`; `tainted` is a resumed checkpoint's taint.
# A2  `await outside.receipts()` is what code shows beside her reply: None when nothing is held or done.
# A3  `outside.tainted` is the origin / first tainting tool's name, None when untainted.
# A4  `HeldCalls.calls` is a tuple of held calls with `.tool`, `.arguments` (a mapping) and `.summary`.
# A5  `CARRY_OUT` is the tool name "carry_out"; `Outside.call` of a held change returns a result that is not the inner's.
# A6  the settings are `app/ashley/tools/outside.json`, keys `max_calls`, `max_argument_chars`, `proposal_ttl_s`.
# A7  `Steps.tainted(tool)` is awaited once, with the tool's name, before the tainting call returns.
# A8  log events `outside.tainted|held|refused|carried_out` carry their fields in `record.fields`, `reason` for refused.
# A9  a refused call (agrees when tainted, too long, too many, not private) returns `is_error`; a held one need not.
# A10 the proposal is stored with `made_by` the speaker and `turn_id` the turn id given in `turn`.
# A11 an `Inbound` with `author="household"` and `taint` set is how a woken turn arrives; the person is `speaker_id`.
# ---------------------------------------------------------------------------------------------------------------------

SETTINGS = json.loads((Path(__file__).parents[2] / "ashley" / "tools" / "outside.json").read_text())
MAX_CALLS = int(SETTINGS["max_calls"])
MAX_CHARS = int(SETTINGS["max_argument_chars"])
TTL_S = float(SETTINGS["proposal_ttl_s"])

READ_OUTSIDE = "web_read"
READ_HOME = "home_read"
READ_DEFAULT = "new_read"
DO = "house_do"
PROMPT = "claude_prompt"
CONFIRM = "house_confirm"
SORT = "mail_sort"
BENCH_ONLY = "bench_edit"
UNKNOWN = "no_such_tool"
EXTRA = "ignored_by_carry_out"


def run(scenario: Any, limit: float = 25.0) -> None:
    run_bounded(scenario, limit)


def spec(name: str, reads: bool = False, outside: bool | None = None, agrees: bool = False) -> ToolSpec:
    return ToolSpec(name, f"{name}", {"type": "object", "properties": {}}, reads, True if outside is None else outside,
                    agrees)


def result(call_id: str, content: str, outside: bool | None = None, is_error: bool = False) -> ToolResult:
    if outside is None:
        return ToolResult(call_id, content, is_error)
    return ToolResult(call_id, content, is_error, outside=outside)


STANDARD = (spec(READ_OUTSIDE, True, True), spec(READ_HOME, True, False), spec(READ_DEFAULT, True),
            spec(DO, False, False), spec(PROMPT, False, False), spec(SORT, False, False),
            spec(CONFIRM, False, False, agrees=True))


class Source(Tools):
    """A scripted inner source: what it offers, what each tool answers, and which calls reached it."""

    def __init__(self, specs: tuple[ToolSpec, ...] = STANDARD) -> None:
        self.specs = specs
        self.calls: list[ToolCall] = []
        self.answers: dict[str, tuple[str, bool | None]] = {}
        self.unseen: set[str] = set()

    async def catalogue(self) -> Catalogue:
        return Catalogue(tuple(s for s in self.specs if s.name not in self.unseen), None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        if call.name not in {s.name for s in self.specs}:
            return ToolResult(call.id, f"no tool named {call.name}", True)
        text, outside = self.answers.get(call.name, (f"{call.name} done", None))
        return result(call.id, text, outside)

    def reached(self, name: str | None = None) -> list[ToolCall]:
        return [c for c in self.calls if name is None or c.name == name]

    def ran(self) -> list[tuple[str, dict[str, object]]]:
        return [(c.name, dict(c.arguments)) for c in self.calls]


class RecordingSteps(Steps):
    def __init__(self, failing: bool = False) -> None:
        self.tainted_by: list[str] = []
        self.failing = failing

    async def tainted(self, tool: str) -> bool:
        if self.failing:
            raise RuntimeError("turn lost")
        self.tainted_by.append(tool)
        return len(self.tainted_by) == 1


@dataclass
class World:
    url: str
    db: PoolDatabase
    store: PostgresProposals
    hid: int
    alana: int
    sam: int
    chat: int
    other_chat: int
    sam_chat: int
    serial: int = 0
    notes: list[str] = field(default_factory=list[str])

    def turn(self, conv: int | None = None, who: int | None = None) -> int:
        """A new person turn, stored after every earlier one."""
        return int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                          "VALUES (%s, %s, 'person', %s, 'yes', 'shared') RETURNING id",
                          (conv or self.chat, self.hid, who or self.alana)))

    def inbound(self, who: int | None = None, taint: str | None = None, author: Literal["person", "household"] = "person",
                audience: Audience = "owner",
                shared: bool = False, device_id: int | None = None, speaker: bool = True) -> Inbound:
        """A turn on the person's own web chat; the arguments make it a woken, shared or unattributed one."""
        person_id = who or self.alana
        kept: dict[str, Any] = {"taint": taint, "author": author, "device_id": device_id,
                                "unprompted": author == "household"}
        return Inbound(self.hid, f"web:{person_id}", "yes", "chat", "text", audience, person_id if speaker else None,
                       shared, None, "web", **kept)

    def wrap(self, source: Tools, inbound: Inbound | None = None, turn: int | None = None, conv: int | None = None,
             steps: Steps = NO_STEPS, tainted: str | None = None) -> Outside:
        got = inbound or self.inbound()
        return Outside(source, standing.of(got), (conv or self.chat, turn or self.turn(conv)), steps,
                       tainted or got.taint)  # A1

    def next_id(self) -> str:
        self.serial += 1
        return f"c{self.serial}"

    async def call(self, o: Tools, name: str, arguments: Mapping[str, object] | None = None) -> ToolResult:
        return await o.call(ToolCall(self.next_id(), name, dict(arguments or {})))

    async def pending(self, who: int | None = None, conv: int | None = None) -> Proposal[Any] | None:
        return await self.store.pending(who or self.alana, conv or self.chat, OUTSIDE)

    async def held(self, who: int | None = None, conv: int | None = None) -> list[tuple[str, dict[str, object]]]:
        got = await self.pending(who, conv)
        return [] if got is None else [(c.tool, dict(c.arguments)) for c in got.payload.calls]  # A4

    def age_proposals(self, seconds: float) -> None:
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute("UPDATE proposals SET created_at = created_at - make_interval(secs => %s)", (seconds,))

    def proposal_rows(self) -> int:
        return int(scalar(self.url, "SELECT count(*) FROM proposals"))


async def names(o: Tools) -> set[str]:
    return {s.name for s in (await o.catalogue()).specs}


async def offers_carry_out(o: Tools) -> bool:
    return CARRY_OUT in await names(o)


@asynccontextmanager
async def opened(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    store = PostgresProposals(db)
    services.register(Proposals, store)
    try:
        hid = household(url, "ta")
        alana, sam = person(url, hid, "Alana"), person(url, hid, "Sam")
        yield World(url, db, store, hid, alana, sam, _conversation(url, hid, alana), _conversation(url, hid, alana),
                    _conversation(url, hid, sam))
    finally:
        services.unregister(Proposals)
        await db.close()


def _conversation(url: str, hid: int, who: int) -> int:
    cid = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (hid,)))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                     "VALUES (%s, %s, %s)", (cid, hid, who))
    return cid


def scenario(url: str, body: Callable[[World], Awaitable[None]]) -> None:
    async def go() -> None:
        async with opened(url) as w:
            await body(w)

    run(go())


async def hold_two(w: World, source: Source | None = None) -> tuple[Source, dict[str, object], dict[str, object]]:
    """A tainted turn of Alana's that held two changes; the source it held them against, and their arguments."""
    got = source or Source()
    o = w.wrap(got, w.inbound(taint="watch"))
    first: dict[str, object] = {"entity": "light.porch", "state": "off"}
    second: dict[str, object] = {"session": "s-9", "prompt": "rm -rf the repo"}
    await w.call(o, DO, first)
    await w.call(o, PROMPT, second)
    got.calls.clear()
    return got, first, second


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[Mapping[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def at_info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)


async def race(*jobs: Awaitable[Any]) -> list[Any]:
    return list(await asyncio.gather(*jobs))
