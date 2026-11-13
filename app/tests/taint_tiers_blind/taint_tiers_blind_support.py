"""Helpers for the blind tests of tiered tainted turns (`~/scratch/ashley/readers-design/design.txt`, sections 1, 2,
2.1, 3.4 and P2): a migrated database with the real proposals store, the real house, mail, reminder, watch and bench
tools behind `Outside`, a spy for the action judge, and readers of the two tables the item adds.

Every guess about a name the item adds is in ASSUMPTIONS below and only here, so the reconciler rewires one file.
Everything else is existing code on main."""

from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from typing import Any, LiteralString

import psycopg
from ashley import services
from ashley.channels import standing
from ashley.channels.model import Audience, Inbound
from ashley.channels.steps import NO_STEPS, Steps
from ashley.senses.proposal_payloads import OUTSIDE
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import Payload, Topic, encode
from ashley.senses.proposals import Proposal, ProposalRefused
from ashley.tools.outside import Standing
from ashley.tools import outside_config
from ashley.tools.outside import Outside
from ashley.senses.outside_record import OutsideRecord
from ashley.senses.postgres_outside_record import PostgresOutsideRecord
from ashley.tools.tools import Catalogue
from contract.conversations_support import household, person
from ashley.db.pool import PoolDatabase
from ashley.inference.model import Tier, ToolCall, ToolResult, ToolSpec
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.proposals import Proposals
from ashley.senses.wakes import Wakes
from ashley.tools.action_judge import ActionJudge, Decision, Reason, Verdict, View
from ashley.tools.tools import Tools
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches
from ashley.workshop import rules as workshop_rules
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from ashley.live.live import Live
from contract.conversations_support import scalar
from contract.conversations_support import run as run_bounded
from ashley.connections.connections import Connections
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Session
from ashley.tools.reminders import ReminderTools
from ashley.tools.watches import WatchTools
from money_support import HeldConnections
from test_watches_claude_session import BASE, FakeBridge
from wake_support import Switchboard
from live_support import FakeLive
from test_reminder_turn import Home

# --- ASSUMPTIONS: every guess, change here only ----------------------------------------------------------------------
# G1  The judge is `ashley.tools.action_judge.ActionJudge` (a `Service`, `ActionJudge.null()` answers ask) with
#     `async decide(words, view) -> Verdict`, `Verdict(decision, reason, explanation)`, decision "run" | "ask".
#     Design 1 says "reached through the service locator"; the module path is a guess.
# G2  A spec's tier is `ToolSpec.tier`, "runs" (tier b) or "judged" (tier c); a spec naming none is judged. Only
#     `TIER_B` is read back (the `tier` column of `outside_actions`).
# G3  Tiers for the house come from `ashley/tools/tiers.json`; `consequential_entities` is a key of the config
#     `ashley.tools.tiers_config.load()` returns, and `HouseTools(..., tiers=<that>)` takes it.
# G4  `Reminder.taint` and `Watch.taint` are `str | None`: the creating turn's taint (a tool name or an origin), None
#     for an untainted turn. A tool stamps it from the turn's taint at the moment it stores (the tool is built with
#     `turn=(conversation, turn)` as on main, and the taint reaches it however the item chooses; the tests only
#     build `Outside(tools, ..., tainted=...)` around the real tool). `taint_the_turn` is the one place to rewire.
# G5  Origin `inherited` is `Inbound.taint == "inherited"`, built by `reminder_turn.inbound` / `watch_turn.inbound`
#     when the stored row's taint is not None.
# G6  `outside_writes(household_id, entity, at)` and `outside_actions(household_id, person_id, conversation_id,
#     turn_id, tool, summary, tier, decision, reason, explanation, at)`: design 2.1 and 3.4 name the columns; the
#     `_id` suffixes follow this schema's convention. `at` is timestamptz.
# G7  Retention of `outside_actions` is 90 days, pruned by the writer on the next write; `outside_writes` keeps an
#     entity as outside for `keep_s` (design A.2), whose value is unknown: tests use ages of 400 days and 1 minute.
# G8  What was done and what is held are `Outside.receipts()`: None when neither exists.
# G9  The reason enum also holds `no_judge` (the Null judge) and `judge_unavailable` (a fault).
#     Events `outside.tier` (every call that a tainted turn classified: tool, tier, decision) and `outside.judged`
#     (a judge consulted: tool, decision, reason, duration_ms) carry fields in `record.fields`; `decision` is "run"
#     or "ask", and `reason` is an enum word (or None/absent for tier b).
# G10 A bench piece edited in a tainted turn reads back through the real BenchTools with `outside` true.
# ---------------------------------------------------------------------------------------------------------------------

TIER_B: Tier = "runs"
HOUSE_ID = 1
OUTSIDE_RETENTION_DAYS = 90
PLANT = "PLANTED-outside-text-7f3a"
REASONS = {"asked_directly", "follows_from_request", "follows_from_brief", "not_asked", "target_not_in_request",
           "exceeds_request", "data_leaves_household", "undoes_safety", "unclear", "no_judge", "judge_unavailable",
           "recipient_unknown", "no_words", "not_junk"}


async def said() -> Sequence[str]:
    """What Alana said, as a turn's `words` reads it."""
    return ("please do that",)


def verdict(decision: Decision, reason: Reason = "unclear") -> Verdict:
    return Verdict(decision, reason, "one sentence")


class SpyJudge(ActionJudge):
    """Records what it was asked; answers `answer`, or fails as `fault` says."""

    def __init__(self, answer: Decision = "ask", fault: str | None = None) -> None:
        self.asked: list[tuple[Any, Any]] = []
        self.answer: Decision = answer
        self.fault = fault

    async def decide(self, words: Any, view: Any) -> Any:
        self.asked.append((words, view))
        if self.fault == "raises":
            raise RuntimeError("provider down")
        if self.fault == "timeout":
            raise TimeoutError("slow")
        if self.fault == "invalid":
            return type("Garbage", (), {"decision": "maybe", "reason": "?", "explanation": ""})()
        return verdict(self.answer)


def agreeing_spec(name: str, tier: Tier = TIER_B) -> ToolSpec:
    """A tool that takes the person's agreement, labelled with a tier (G2) to show agreeing outranks it."""
    return ToolSpec(name, name, {"type": "object", "properties": {}}, agrees=True, tier=tier)


def seen_by(judge: SpyJudge) -> str:
    return repr(judge.asked)


async def ask_null(words: tuple[str, ...] = ("turn it on",), view: View | None = None) -> Any:
    return await ActionJudge.null().decide(words, view or View("house_do"))


def spec(name: str, reads: bool = False, outside: bool = False) -> ToolSpec:
    return ToolSpec(name, name, {"type": "object", "properties": {}}, reads, outside=outside)


class Source(Tools):
    """A scripted inner source: what it offers, what each tool answers (`answers`: text and `outside`), and which calls
    reached it."""

    def __init__(self, specs: tuple[ToolSpec, ...]) -> None:
        self.specs = specs
        self.calls: list[ToolCall] = []
        self.answers: dict[str, tuple[str, bool | None]] = {}

    async def catalogue(self) -> Catalogue:
        return Catalogue(self.specs, None)

    async def call(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        text, outside = self.answers.get(call.name, (f"{call.name} done", None))
        return ToolResult(call.id, text) if outside is None else ToolResult(call.id, text, outside=outside)

    def reached(self, name: str | None = None) -> list[ToolCall]:
        return [c for c in self.calls if name is None or c.name == name]


@dataclass
class World:
    """A household of Alana and Sam, Alana's web chat, and the real proposals store."""

    url: str
    db: PoolDatabase
    store: PostgresProposals
    hid: int
    alana: int
    sam: int
    chat: int
    serial: int = 0

    def turn(self) -> int:
        """A new person turn, stored after every earlier one."""
        return int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, "
                          "visibility) VALUES (%s, %s, 'person', %s, 'yes', 'shared') RETURNING id",
                          (self.chat, self.hid, self.alana)))

    def inbound(self, taint: str | None = None, audience: Audience = "owner") -> Inbound:
        kept: dict[str, Any] = {"taint": taint}
        return Inbound(self.hid, f"web:{self.alana}", "yes", "chat", "text", audience, self.alana, False, None, "web",
                       **kept)

    def wrap(self, source: Tools, inbound: Inbound | None = None, turn: int | None = None, conv: int | None = None,
             steps: Steps = NO_STEPS, tainted: str | None = None) -> Outside:
        got = inbound or self.inbound()
        return Outside(source, standing.of(got), (conv or self.chat, turn or self.turn()), steps, tainted or got.taint,
                            words=said)

    async def call(self, o: Tools, name: str, arguments: Mapping[str, object] | None = None) -> ToolResult:
        self.serial += 1
        return await o.call(ToolCall(f"c{self.serial}", name, dict(arguments or {})))

    async def held(self) -> list[tuple[str, dict[str, object]]]:
        found = await self.store.pending(self.alana, self.chat, OUTSIDE)
        return [] if found is None else [(c.tool, dict(c.arguments)) for c in found.payload.calls]


@asynccontextmanager
async def opened(url: str) -> AsyncGenerator[World]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    store = PostgresProposals(db)
    services.register(Proposals, store)
    shipped = outside_config.load()
    services.register(OutsideRecord, PostgresOutsideRecord(db, shipped.actions_keep_s, shipped.writes_keep_s))
    try:
        hid = household(url, "tt")
        assert hid == HOUSE_ID, "a fresh test database numbers its first household 1"
        alana, sam = person(url, hid, "Alana"), person(url, hid, "Sam")
        cid = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (hid,)))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                         "VALUES (%s, %s, %s)", (cid, hid, alana))
        yield World(url, db, store, hid, alana, sam, cid)
    finally:
        services.unregister(Proposals)
        services.unregister(OutsideRecord)
        await db.close()


def taint_the_turn(inner: Tools, w: World, tainted: str | None, conv: int | None = None, turn: int | None = None,
                   inbound: Inbound | None = None) -> Outside:
    """`Outside` over `inner` for a person turn of Alana's, already tainted by `tainted` (G4)."""
    return w.wrap(inner, inbound or w.inbound(), turn=turn, conv=conv, tainted=tainted)


@dataclass
class Tiered:
    """The database world plus the registrations the real reminder, watch and bench tools need."""

    w: World
    home: int
    alana: int
    wakes: Wakes
    watches: Watches
    shop: Workshop
    extra: dict[str, Any] = field(default_factory=dict[str, Any])

    def sql(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        return scalar(self.w.url, query, params)

    def exec(self, query: LiteralString, params: tuple[Any, ...] = ()) -> None:
        with psycopg.connect(self.w.url, autocommit=True) as conn:
            conn.execute(query, params)

    def actions(self) -> list[dict[str, Any]]:
        """Rows of `outside_actions`, oldest first (G6)."""
        got = self.sql("SELECT coalesce(json_agg(a ORDER BY a.at, a.tool), '[]') FROM "
                       "(SELECT tool, tier, decision, reason, explanation, conversation_id, turn_id, summary, at "
                       "FROM outside_actions) a")
        return list(got)

    def writes(self) -> list[str]:
        return [str(e) for e in self.sql("SELECT coalesce(json_agg(entity ORDER BY entity), '[]') FROM outside_writes")]


@asynccontextmanager
async def tiered(url: str) -> AsyncGenerator[Tiered]:
    async with opened(url) as w:
        db = w.db
        people = (Person(w.alana, w.hid, "Alana"), Person(w.sam, w.hid, "Sam"))
        wired: dict[Any, Any] = {People: Home(Household(w.hid, "home", "America/Denver", "", people)),
                                 Wakes: PostgresWakes(db), Watches: PostgresWatches(db), Live: FakeLive(),
                                 Workshop: PostgresWorkshop(db, workshop_rules.load())}
        for interface, provider in wired.items():
            services.register(interface, provider)
        try:
            yield Tiered(w, w.hid, w.alana, wired[Wakes], wired[Watches], wired[Workshop])
        finally:
            for interface in wired:
                services.unregister(interface)


SESSIONS = (Session("s1", "build", "/d", "working", 4, None), Session("s2", "docs", "/d", "done", 9, None))


def reminder_tools(t: Tiered, turn: tuple[int, int] | None = None) -> ReminderTools:
    return ReminderTools(t.home, t.alana, private=True, turn=turn or (t.w.chat, 0), usable=lambda: Switchboard())


def watch_tools(t: Tiered, turn: tuple[int, int] | None = None) -> WatchTools:
    """Real watch tools over a fake bridge that lists sessions s1 and s2; the services they need stay wired for the test."""
    held = HeldConnections()
    held.connect(t.home, BASE, "tok", "herdr", t.alana)
    for interface, provider in ((Connections, held), (Bridge, FakeBridge(SESSIONS)), (Proposals, PostgresProposals(t.w.db))):
        services.register(interface, provider)
    return WatchTools(t.home, t.alana, turn=turn or (t.w.chat, 0), usable=lambda: Switchboard())


def scenario(url: str, body: Callable[[Tiered], Awaitable[None]], limit: float = 40.0) -> None:
    async def go() -> None:
        async with tiered(url) as t:
            await body(t)

    run_bounded(go(), limit)


def events(caplog: Any, event: str) -> list[Mapping[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def held_tools(held: list[tuple[str, dict[str, object]]]) -> list[str]:
    return [t for t, _ in held]


READ_OUTSIDE, PROMPT, DO = "web_read", "claude_prompt", "house_do"
CARRY_OUT = "carry_out"


async def hold_two(w: World) -> tuple[dict[str, object], dict[str, object]]:
    """A turn tainted by its origin that held two changes (judged under the Null judge); their arguments."""
    src = Source((spec(DO), spec(PROMPT)))
    o = w.wrap(src, w.inbound(taint="watch"))
    first: dict[str, object] = {"entity": "light.porch", "state": "off"}
    second: dict[str, object] = {"session": "s-9", "prompt": "rm -rf the repo"}
    await w.call(o, DO, first)
    await w.call(o, PROMPT, second)
    return first, second


SPEAKER, HOUSEHOLD, CONVERSATION, TURN = 7, 1, 40, 100
STANDING = Standing(HOUSEHOLD, SPEAKER, private=True, agreeing=True)


def run(scenario_: Coroutine[Any, Any, None]) -> None:
    run_bounded(scenario_, 10.0)


def asked(name: str, call_id: str = "c1", **arguments: object) -> ToolCall:
    return ToolCall(call_id, name, arguments)


class Memory(Proposals):
    """Proposals in a dict keyed as the Postgres store keys them (person-scoped for the outside topic)."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, str, int | None], Proposal[Any]] = {}

    async def propose[P: Payload](self, proposal: Proposal[P], ttl_s: float) -> int:
        name, _ = encode(proposal.payload)
        self.rows[(proposal.made_by, name, None if name == "outside" else proposal.conversation_id)] = replace(
            proposal, id=len(self.rows) + 1)
        return len(self.rows)

    async def pending[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P]) -> Proposal[P] | None:
        return self.rows.get((made_by, topic.name, None if topic.scope == "person" else conversation_id))

    async def take[P: Payload](self, made_by: int, conversation_id: int, topic: Topic[P], turn_id: int,
                               ttl_s: float) -> Proposal[P]:
        raise ProposalRefused("none")

    async def find[P: Payload](self, proposal_id: int, topic: Topic[P]) -> Proposal[P] | None:
        raise AssertionError("not used")

    async def take_by_id[P: Payload](self, proposal_id: int, topic: Topic[P], made_by: int, turn_id: int,
                                     ttl_s: float) -> Proposal[P]:
        raise AssertionError("not used")
