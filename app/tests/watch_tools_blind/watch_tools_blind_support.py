"""Helpers for the blind WatchTools tests (`decisions.md`, "Watches wake her when what a read returns changes", its "Her
tools" paragraph): a household of Alana and Sam in Denver, connections held in memory, an in-memory `Watches` store and
kinds swapped into the app's one registry that record what the tools ask of them, an in-memory `Proposals`, and calls on `WatchTools` by name.

ASSUMPTIONS (every guess beyond the design; change here only, listed with the spec phrase each rests on in
~/scratch/ashley/watches/watch-tools-blind/assumptions.txt):
  A1  `ashley.tools.watches.WatchTools(household_id, speaker_id, *, turn=None, usable=None, bench_id=None)`, the
      constructor shaped as `ReminderTools`'s; `channels.turn_tools.sources` offers it under the key `watches`.
  A2  Module homes: `ashley.watches.watches` holds `Watches`, `WatchesUnavailable`; `ashley.watches.model` holds `Arm`,
      `Armed`, `Watch`, `ReadFailed`; kinds live in `ashley.watches.registry.KINDS`, their numbers in `CONFIG.kinds`.
  A3  A `Kind` has `name`, `port` (the connection port it reads through), `track`, `when`, `interval_s`, `hours`,
      `max_hours` and `async read(group)`; a read answers a mapping from a watch key to `Items | ReadFailed`, and
      `Items` is a mapping of item id to tracked fields carrying `.labels` (item id to display label).
  A4  The tools are `watch`, `unwatch` and `watches`; arguments are exactly as the spec names them; an error result
      starts with its outcome (`bench_results.failed`): `bad_arguments`, `not_found`, `not_connected`, `unavailable`.
  A5  `watch` answers JSON with a label, the tracked fields now and the expiry (`body` reads the build's `now` and
      `ends` as `tracked` and `expires`; a paused row's `paused` as `reason`; household wall clock,
      `senses.repeat.LOCAL_FORMAT`); a proposed watch answers `armed: false` and the `tools`, as a reminder does.
  A6  A predicate in `until` is `{"kind", "not", "field", "value", "values", "min", "max", "text", "of"}`, the money
      clause's `not` for negation; it reaches the store as `criteria.items.ItemPredicate` tuples.
  A7  `Arm` has `household_id, person_id, kind, target, label, bench_id, armed_by, track, when, until, tools,
      interval_s, expires_at, baseline` (the spec's list); `Armed` has `id`, `new`; a watch omitting `until` arms with
      `until == ()`, `when` is the kind's, `armed_by == "ashley"`, `interval_s` the kind's, `tools` None when none named.
  A8  `WatchSchedule` carries the watch's kind, target and the reminder's person and tools; it is proposed in the
      `REMINDERS` topic, and the baseline is the read at agreement.
  A9  A live `Watch` shows `kind, target, label, until (Condition), expires_at, state ("armed" | "paused"), reason`;
      `watches` lists them as `{"watches": [{kind, label, until, expires, [reason]}]}`, `reason` only when paused.
  A10 A catalogue is empty (not raising) for a person with no source; with Connections down it raises
      ToolsUnavailable, as `ClaudeCodeTools` does.
"""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from money_support import HeldConnections
from watch_tools_blind_fakes import (
    ACT,
    ALANA,
    CONVERSATION,
    DENVER,
    HOUSE,
    KIND,
    READ,
    SAM,
    TARGET,
    FakeKind,
    FakeKinds,
    FakeProposals,
    FakeWatches,
    Folk,
    Shelf,
    items,
)

from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.logs import Logfmt
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.proposals import Proposal, Proposals
from ashley.senses.repeat import LOCAL_FORMAT
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Tools
from ashley.tools.watches import WatchTools
from ashley.watches.watches import Watches


@dataclass
class World:
    store: FakeWatches
    kind: FakeKind
    kinds: FakeKinds
    proposals: FakeProposals
    connections: HeldConnections
    shelf: Shelf = field(default_factory=lambda: Shelf(READ, ACT))

    def tools(self, speaker: int = ALANA, turn: tuple[int, int] | None = (CONVERSATION, 10), shelf: Shelf | None = None,
              bench_id: int | None = None) -> WatchTools:
        kept = self.shelf if shelf is None else shelf
        return WatchTools(HOUSE, speaker, turn=turn, usable=lambda: kept, bench_id=bench_id)

    def reminders(self, turn: int) -> ReminderTools:
        return ReminderTools(HOUSE, ALANA, private=True, turn=(CONVERSATION, turn), usable=lambda: self.shelf)


@asynccontextmanager
async def world(connected: bool = True, answer: Any = "default", extra: tuple[FakeKind, ...] = ()) -> AsyncGenerator[World]:
    """Alana has connected a herdr bridge (unless `connected` is False); the kind reads `answer` (the two sessions by
    default)."""
    kind = FakeKind(answer=items() if answer == "default" else answer)
    for other in extra:
        if other.answer is None:
            other.answer = items()
    store, proposals, held = FakeWatches(), FakeProposals(), HeldConnections()
    if connected:
        held.connect(HOUSE, "https://127.0.0.1:7843", "tok", "herdr", ALANA)
    kinds = FakeKinds(kind, *extra)
    people = (Person(ALANA, HOUSE, "Alana"), Person(SAM, HOUSE, "Sam"))
    wired: dict[Any, Any] = {People: Folk(Household(HOUSE, "home", DENVER.key, "", people)), Connections: held,
                             Watches: store, Proposals: proposals}
    for interface, provider in wired.items():
        services.register(interface, provider)
    kinds.install()
    try:
        yield World(store, kind, kinds, proposals, held)
    finally:
        kinds.restore()
        for interface in wired:
            services.unregister(interface)


def plain(**more: Any) -> dict[str, Any]:
    return {"kind": KIND, "target": TARGET, **more}


async def use(tools: Tools, name: str, args: dict[str, Any] | None = None) -> ToolResult:
    return await tools.call(ToolCall("c1", name, {} if args is None else args))


async def offered(tools: Tools) -> list[str]:
    return [s.name for s in (await tools.catalogue()).specs]


async def spec_of(tools: Tools, name: str) -> ToolSpec:
    return next(s for s in (await tools.catalogue()).specs if s.name == name)


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loaded: dict[str, Any] = json.loads(result.content)
    for built, assumed in (("now", "tracked"), ("ends", "expires")):
        if built in loaded and assumed not in loaded:
            loaded[assumed] = loaded[built]
    if "tracked" in loaded:
        loaded["tracked"] = _unwrapped(loaded["tracked"])
    rows: Any = loaded.get("watches", ())
    for row in rows:
        if "paused" in row:
            row["reason"] = row["paused"]
    return loaded


def _unwrapped(now: Any) -> Any:
    """The one target's fields when the read is keyed by target."""
    one: Any = now
    return next(iter(one.values())) if hasattr(one, "values") and len(one) == 1 else one


def logline(record: logging.LogRecord) -> str:
    """The record as the logfmt line the process writes."""
    return Logfmt().format(record)


@dataclass(frozen=True)
class Proposed:
    """What a proposed watch will arm, read from the `WatchSchedule` payload."""

    kind: str
    target: str
    person_id: int
    tools: tuple[str, ...] | None


def proposed_arm(proposal: Proposal[Any]) -> Proposed:
    schedule = proposal.payload
    return Proposed(schedule.kind, schedule.target, schedule.reminder.person_id, schedule.reminder.tools)


def refused(result: ToolResult, outcome: str | None = None) -> None:
    assert result.is_error, result.content
    if outcome is not None:
        assert result.content.startswith(outcome), result.content


def clause(*predicates: dict[str, Any]) -> list[dict[str, Any]]:
    return list(predicates)


def local(when: datetime) -> str:
    return when.astimezone(DENVER).strftime(LOCAL_FORMAT)


def minutes_from_now(when: datetime, minutes: float, slack_s: float = 120.0) -> bool:
    return abs((when - datetime.now(UTC) - timedelta(minutes=minutes)).total_seconds()) <= slack_s


def inbound(**more: Any) -> Inbound:
    base = Inbound(household_id=HOUSE, thread="person:11:web", text="hi", kind="chat", medium="text", audience="owner",
                   speaker_id=ALANA, shared=False, place=None, channel="web", later=True, later_by="turn",
                   opens_benches=True, on_page=True)
    return replace(base, **more)


def source_keys(turn: Inbound) -> set[str]:
    return set(sources(turn))


def predicate(kind: str, **fields: Any) -> dict[str, Any]:
    return {"kind": kind, **fields}


def schema_of(spec: ToolSpec) -> dict[str, Any]:
    """The spec's argument schema as plain JSON."""
    loaded: dict[str, Any] = json.loads(json.dumps(spec.parameters))
    return loaded
