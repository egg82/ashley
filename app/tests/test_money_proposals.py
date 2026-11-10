"""A money reminder is armed only after the person has answered (`ashley.senses.deposits.refusal`, `take`):
`remind_on_money` stores a proposal and arms nothing; `arm_money_reminder` takes the proposal only from a later person turn
of the same conversation, by the person who proposed it, before it expires, once. Turn ids decide, never words."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.proposal_payloads import REMINDERS, MoneyRule
from ashley.senses.proposals import Proposal, ProposalRefused, refusal
from ashley.senses.wakes import Reminder
from ashley.tools import reminder_specs as specs
from ashley.tools.reminders import ReminderTools
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar
from deposit_support import House, house
from money_support import CHECKING

NOW = datetime(2026, 11, 3, 15, tzinfo=UTC)
ARGS: dict[str, object] = {"for": "Alana", "direction": "in", "account_id": CHECKING, "account": "Checking",
                           "min_amount": 500, "what": "move it"}


def proposal() -> Proposal[MoneyRule]:
    return Proposal(1, 7, 4, 10, NOW, MoneyRule(Reminder(1, 7, 7, "x", NOW, None), DepositRule("a", "A", 1)))


def test_a_proposal_is_armed_from_a_later_turn_within_its_time_only() -> None:
    soon, late = NOW + timedelta(hours=1), NOW + timedelta(hours=3)
    assert refusal(proposal(), 11, soon, 7200) is None
    assert refusal(proposal(), 10, soon, 7200) == "same_turn"
    assert refusal(proposal(), 9, soon, 7200) == "same_turn"
    assert refusal(proposal(), 11, late, 7200) == "expired"


async def tool(h: House, who: int, conversation: int, turn: int, name: str, args: dict[str, object]) -> ToolResult:
    return await ReminderTools(h.home, who, private=True, turn=(conversation, turn)).call(ToolCall("c", name, args))


def test_a_proposal_arms_nothing_and_is_armed_only_from_a_later_turn_by_its_person_once(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            sam = person(db_url, h.home, "Sam")
            made = await tool(h, h.alana, 1, 5, specs.ON_MONEY, ARGS)
            assert not made.is_error and json.loads(made.content)["armed"] is False and await h.deposits.armed() == ()
            for who, conversation, turn, why in [(h.alana, 1, 5, "same_turn"), (h.alana, 1, 4, "same_turn"),
                                                 (h.alana, 2, 6, "none"), (sam, 1, 6, "none")]:
                refused = await tool(h, who, conversation, turn, specs.ARM, {})
                assert refused.is_error and refused.content.startswith(why), (who, conversation, turn)
            assert await h.deposits.armed() == ()
            armed = await tool(h, h.alana, 1, 6, specs.ARM, {})
            (got,) = await h.deposits.armed()
            assert not armed.is_error and got.rule.min_cents == 50_000 and got.id == json.loads(armed.content)["id"]
            again = await tool(h, h.alana, 1, 7, specs.ARM, {})
            assert again.is_error and again.content.startswith("none") and len(await h.deposits.armed()) == 1
    run(go())


def test_the_latest_proposal_is_the_one_armed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await tool(h, h.alana, 1, 5, specs.ON_MONEY, {**ARGS, "min_amount": 500})
            await tool(h, h.alana, 1, 6, specs.ON_MONEY, {**ARGS, "min_amount": 900})
            same = await tool(h, h.alana, 1, 6, specs.ARM, {})
            assert same.is_error and same.content.startswith("same_turn")
            await tool(h, h.alana, 1, 7, specs.ARM, {})
            (got,) = await h.deposits.armed()
            assert got.rule.min_cents == 90_000
    run(go())


def test_an_expired_proposal_is_refused_and_old_ones_are_dropped_when_another_is_made(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await tool(h, h.alana, 1, 5, specs.ON_MONEY, ARGS)
            with pytest.raises(ProposalRefused) as late:
                await h.proposals.take(h.alana, 1, REMINDERS, 6, ttl_s=-1)
            assert late.value.reason == "expired" and await h.deposits.armed() == ()
            scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = now() - interval '2 days' RETURNING 1) "
                           "SELECT count(*) FROM u")
            await tool(h, h.alana, 1, 7, specs.ON_MONEY, ARGS)
            assert scalar(db_url, "SELECT count(*) FROM proposals") == 1
    run(go())


def test_without_a_turn_she_can_neither_propose_nor_arm(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            bare = ReminderTools(h.home, h.alana, private=True)
            for name, args in [(specs.ON_MONEY, ARGS), (specs.ARM, {})]:
                got = await bare.call(ToolCall("c", name, args))
                assert got.is_error and got.content.startswith("unavailable")
            assert specs.ARM not in [s.name for s in (await bare.catalogue()).specs]
    run(go())


async def offered(h: House, turn: int) -> bool:
    got = await ReminderTools(h.home, h.alana, private=True, turn=(1, turn)).catalogue()
    return specs.ARM in [s.name for s in got.specs]


def test_she_is_offered_arming_only_in_a_turn_after_a_proposal_of_hers(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            assert not await offered(h, 5)
            await tool(h, h.alana, 1, 5, specs.ON_MONEY, ARGS)
            assert not await offered(h, 5) and await offered(h, 6)
            other = ReminderTools(h.home, h.alana, private=True, turn=(2, 6))
            assert specs.ARM not in [s.name for s in (await other.catalogue()).specs]
            await tool(h, h.alana, 1, 6, specs.ARM, {})
            assert not await offered(h, 7)
    run(go())


def test_a_second_proposal_replaces_the_first_so_one_agreement_arms_one_rule(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await tool(h, h.alana, 1, 5, specs.ON_MONEY, {**ARGS, "min_amount": 500})
            await tool(h, h.alana, 1, 5, specs.ON_MONEY, {**ARGS, "min_amount": 700})
            assert not (await tool(h, h.alana, 1, 6, specs.ARM, {})).is_error
            second = await tool(h, h.alana, 1, 6, specs.ARM, {})
            assert second.is_error and second.content.startswith("none")
            (got,) = await h.deposits.armed()
            assert got.rule.min_cents == 70_000
    run(go())


def test_the_guidance_names_arming_only_in_a_turn_where_it_is_offered(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            before = await ReminderTools(h.home, h.alana, private=True, turn=(1, 5)).catalogue()
            await tool(h, h.alana, 1, 5, specs.ON_MONEY, ARGS)
            same = await ReminderTools(h.home, h.alana, private=True, turn=(1, 5)).catalogue()
            later = await ReminderTools(h.home, h.alana, private=True, turn=(1, 6)).catalogue()
            for got, offered_arm in [(before, False), (same, False), (later, True)]:
                names = [s.name for s in got.specs]
                text = (got.instructions or "") + " ".join(s.description for s in got.specs if s.name != specs.ARM)
                assert (specs.ARM in names) is offered_arm
                assert (specs.ARM in text) is offered_arm, offered_arm
    run(go())


def test_proposing_drops_proposals_older_than_the_ttl_and_keeps_the_younger(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await tool(h, h.alana, 1, 5, specs.ON_MONEY, ARGS)
            await tool(h, h.alana, 2, 5, specs.ON_MONEY, ARGS)
            scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = now() - interval '36 hours' "
                           "WHERE conversation_id = 1 RETURNING 1) SELECT count(*) FROM u")
            scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = now() - interval '12 hours' "
                           "WHERE conversation_id = 2 RETURNING 1) SELECT count(*) FROM u")
            await tool(h, h.alana, 3, 5, specs.ON_MONEY, ARGS)
            assert scalar(db_url, "SELECT array_agg(conversation_id ORDER BY conversation_id) FROM proposals") == [2, 3]
    run(go())
