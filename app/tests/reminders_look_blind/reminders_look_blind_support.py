"""Pieces of the reminder-look blind tests: a Tools source whose specs say which of them read, the deposit a reminder
carries with sentinel values that must never reach a log, and reminders and turns built on them."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from ashley.channels.model import Inbound
from ashley.channels.wake.reminder_turn import inbound as reminder_inbound
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Account, Household, Person
from ashley.people.people import People
from ashley.senses.deposit_rule import Landed
from ashley.senses.wakes import Reminder
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable

PAYEE = "ZQPayeeSentinel7731"
ACCOUNT = "ZQAccountSentinel7731"
CENTS = 98_765_432
AMOUNT_FORMS = ("98765432", "987654.32", "987,654.32", "987654,32")
DAY = date(2026, 11, 3)
LANDED = Landed(CENTS, DAY, ACCOUNT, PAYEE)
BRIEF = "move whatever landed to joint savings"
ALANA = Person(11, 5, "Alana")
SAM = Person(12, 5, "Sam")


def spec(name: str, reads: bool) -> ToolSpec:
    return ToolSpec(name, f"the {name} tool", {"type": "object", "properties": {"a": {"type": "string"}}}, reads=reads)


class Listed(Tools):
    """A source offering `specs`, answering each call with `done:<name>`; `down` makes it unreachable."""

    def __init__(self, specs: tuple[ToolSpec, ...], down: bool = False, unreachable: tuple[str, ...] = (),
                 instructions: str | None = None) -> None:
        self.specs, self.down, self.unreachable, self.instructions = specs, down, unreachable, instructions
        self.called: list[str] = []

    async def catalogue(self) -> Catalogue:
        if self.down:
            raise ToolsUnavailable("down")
        return Catalogue(self.specs, self.instructions, self.unreachable)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call.name)
        return ToolResult(call.id, f"done:{call.name}")


class Home(People):
    """Household 5 of Alana and Sam, which the reminder tools read their people from."""

    async def household(self, household_id: int) -> Household | None:
        return Household(5, "home", "America/Denver", "", (ALANA, SAM)) if household_id == 5 else None

    async def person_for(self, system: str, external_id: str) -> Person | None:
        return None

    async def accounts(self, household_id: int, system: str) -> tuple[Account, ...]:
        return ()


READS = ("look_up", "balance")
CHANGES = ("lamp_on", "HassTurnOn", "send_money")


def mixed() -> Listed:
    """Two tools that read and three that change something, interleaved."""
    order = ("look_up", "lamp_on", "balance", "HassTurnOn", "send_money")
    return Listed(tuple(spec(n, n in READS) for n in order))


def names(catalogue: Catalogue) -> list[str]:
    return [s.name for s in catalogue.specs]


def offered(tools: Tools) -> list[str]:
    return names(asyncio.run(tools.catalogue()))


def called(tools: Tools, name: str) -> ToolResult:
    return asyncio.run(tools.call(ToolCall("c1", name, {})))


def reminder(landed: Landed | None = LANDED, brief: str = BRIEF, who: Person = ALANA, house: int = 5) -> Reminder:
    return Reminder(house, who.id, who.id, brief, datetime(2026, 11, 3, 15, 0, tzinfo=UTC), None, landed)


def turn(landed: Landed | None = LANDED, who: Person = ALANA, **changes: Any) -> Inbound:
    return replace(reminder_inbound(31, reminder(landed, who=who), who, who), **changes)
