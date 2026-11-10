"""Arming the sort through her tools, for the blind tests (`decisions.md`, "The inbox watch and the sort"): the real
`WatchTools` and `ReminderTools` over a `mail_inbox` kind that reads one message, a store that records each `Arm`, and
proposals in memory, in a household of one person.

  G6  `watch` takes `brief` (a string) and `standing` (a boolean) beside `kind`, `target`, `until`, `hours` and `tools`; a
      malformed one is `bad_arguments`. `watch` with `tools` naming one that acts is proposed (`armed` false);
      `arm_reminder` of a later person turn arms it with the fields as proposed.
  G8  `ashley.watches.mail_inbox.MailInbox.available(household_id, person_id)` is true when `ConnectionResources.usable`
      gives the person a mailbox and false when it gives none."""

import json
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from ashley import services
from ashley.connections.connections import Connections
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.proposals import Proposals
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Catalogue, Tools
from ashley.tools.watches import WatchTools
from ashley.watches.kinds import Kind
from ashley.watches.model import Arm, Armed, Read, Watch
from ashley.watches.registry import KINDS
from ashley.watches.watches import Watches
from mail_sort_blind_support import ADDRESS, ITEMS
from mail_sort_blind_turn_support import CONVERSATION, HOUSEHOLD, PERSON, Held
from money_support import HeldConnections

_SLOT = "_kinds"
ACTING = ("mail_search", "mail_label")
SHELF = (ToolSpec("mail_search", "search", {"type": "object"}, reads=True, outside=True),
         ToolSpec("mail_label", "label", {"type": "object"}, reads=False, outside=False),
         ToolSpec("mail_send", "send", {"type": "object"}, reads=False, outside=False))


class Inbox(Kind):
    """A `mail_inbox` kind that reads one message and says its mailboxes are connected."""

    name = "mail_inbox"
    empty_is_absent = False

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        return {w.id: ITEMS for w in group}

    async def available(self, household_id: int, person_id: int) -> bool:
        return True


class Folk(People):
    async def household(self, household_id: int) -> Household | None:
        return Household(HOUSEHOLD, "home", "America/Denver", "", (Person(PERSON, HOUSEHOLD, "Alana"),))

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


@dataclass
class Recording(Watches):
    """A store that records each `arm`; nothing else is asked of it."""

    armed: list[Arm] = field(default_factory=list[Arm])

    async def arm(self, arm: Arm) -> Armed:
        self.armed.append(arm)
        return Armed(len(self.armed), True)

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        raise AssertionError("not asked")

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        return ()

    async def get(self, watch_id: int) -> Watch | None:
        raise AssertionError("not asked")

    async def due(self, limit: int) -> tuple[Watch, ...]:
        raise AssertionError("not asked")

    async def record(self, watch_id: int, version: int, check: Any) -> bool:
        raise AssertionError("not asked")

    async def expire(self, keep_s: float) -> Any:
        raise AssertionError("not asked")


class Shelf(Tools):
    """The tools the speaker has in this turn, which a watch may name."""

    async def catalogue(self) -> Catalogue:
        return Catalogue(SHELF, None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "{}")


@dataclass
class Arming:
    store: Recording
    proposals: Held

    def watch(self, turn: int = 10) -> WatchTools:
        return WatchTools(HOUSEHOLD, PERSON, turn=(CONVERSATION, turn), usable=Shelf)

    def reminders(self, turn: int) -> ReminderTools:
        return ReminderTools(HOUSEHOLD, PERSON, private=True, turn=(CONVERSATION, turn), usable=Shelf)


def sort_args(**more: Any) -> dict[str, Any]:
    return {"kind": "mail_inbox", "target": ADDRESS, "tools": list(ACTING), "standing": True,
            "brief": "sort what is in the inbox", **more}


async def use(tools: Tools, name: str, args: Mapping[str, Any] | None = None) -> ToolResult:
    return await tools.call(ToolCall("c1", name, dict(args or {})))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loaded: dict[str, Any] = json.loads(result.content)
    return loaded


@asynccontextmanager
async def arming() -> AsyncGenerator[Arming]:
    store, proposals = Recording(), Held()
    wired: dict[Any, Any] = {People: Folk(), Connections: HeldConnections(), Watches: store, Proposals: proposals}
    for interface, provider in wired.items():
        services.register(interface, provider)
    kept = dict(getattr(KINDS, _SLOT))
    setattr(KINDS, _SLOT, {**kept, "mail_inbox": Inbox()})
    try:
        yield Arming(store, proposals)
    finally:
        setattr(KINDS, _SLOT, kept)
        for interface in wired:
            services.unregister(interface)
