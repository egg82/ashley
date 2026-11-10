"""Pieces of the proposal blind tests: her money tools for a given conversation and turn, and calls with the fields a
`remind_on_money` needs."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.proposal_payloads import MoneyRule, ReminderPayload
from ashley.senses.proposals import Proposal
from ashley.senses.wakes import Reminder
from ashley.tools import reminder_specs as specs
from ashley.tools.reminders import ReminderTools
from deposit_support import House
from money_support import CHECKING

CONVERSATION = 7


def proposal_args(**more: object) -> dict[str, object]:
    return {"for": "Alana", "direction": "in", "account_id": CHECKING, "account": "Checking",
            "what": "Your bonus landed: move it to joint savings.", "payee": "KVR", **more}


@dataclass
class Talk:
    """One person in one conversation: each `say(turn)` is the tools of that person turn."""

    h: House
    conversation: int = CONVERSATION
    who: int | None = None

    def say(self, turn: int) -> ReminderTools:
        return ReminderTools(self.h.home, self.h.alana if self.who is None else self.who, private=True,
                             turn=(self.conversation, turn))

    async def propose(self, turn: int, **more: object) -> ToolResult:
        return await self.say(turn).call(ToolCall(f"p{turn}", specs.ON_MONEY, proposal_args(**more)))

    async def arm(self, turn: int) -> ToolResult:
        return await self.say(turn).call(ToolCall(f"a{turn}", specs.ARM, {}))

    async def offered(self, turn: int) -> list[str]:
        return [s.name for s in (await self.say(turn).catalogue()).specs]


def stored(h: House, rule: DepositRule, conversation: int, turn: int, age: timedelta = timedelta(0),
           who: int | None = None) -> Proposal[MoneyRule]:
    owner = h.alana if who is None else who
    reminder = Reminder(h.home, owner, owner, "Move it to joint savings.", datetime.now(UTC) - age, None)
    return Proposal(h.home, owner, conversation, turn, datetime.now(UTC) - age, MoneyRule(reminder, rule))


def money(found: Proposal[ReminderPayload] | None) -> MoneyRule:
    """The money rule of a pending proposal that is one."""
    assert found is not None and isinstance(found.payload, MoneyRule)
    return found.payload
