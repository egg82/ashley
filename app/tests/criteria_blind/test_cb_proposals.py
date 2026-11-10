"""`remind_on_money` only proposes; `arm_reminder` arms the latest proposal of hers in the conversation from a later
person turn; she is offered it only after a proposal of hers from an earlier turn; a newer proposal replaces older ones."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pytest
from ashley.inference.model import ToolCall
from ashley.senses import deposit_sense
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.proposal_payloads import REMINDERS, MoneyRule
from ashley.senses.proposals import Proposal, ProposalRefused, refusal
from ashley.senses.wakes import Reminder
from ashley.tools import reminder_specs as specs
from ashley.tools.reminders import ReminderTools
from cb_tools_support import CONVERSATION, Talk, money, proposal_args, stored
from contract.conversations_support import person, run, scalar
from criteria_blind_support import above, new_payer, payee
from deposit_support import NOW, DepositSure, deposit, house
from money_support import CHECKING

TTL = 86_400.0


def test_the_proposals_table_exists_in_a_migrated_database(db_url: str) -> None:
    assert scalar(db_url, "SELECT to_regclass('proposals')::text") == "proposals"




def test_remind_on_money_proposes_and_arms_nothing_in_words(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            made = await Talk(h).propose(10)
            assert not made.is_error and "KVR" in made.content
            assert await h.deposits.armed() == ()
            got = await h.proposals.pending(h.alana, CONVERSATION, REMINDERS)
            assert got is not None and got.turn_id == 10 and got.conversation_id == CONVERSATION
            kept = money(got)
            assert kept.rule == DepositRule(CHECKING, "Checking", None, "KVR", "contains")
            assert kept.reminder.brief == proposal_args()["what"] and kept.reminder.person_id == h.alana

    run(go())


def test_the_proposal_keeps_the_conditions_and_the_judge_flag_she_gave(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            made = await Talk(h).propose(10, conditions=[[{"kind": "payee", "text": "KVR"},
                                                         {"kind": "amount_vs_usual", "above_pct": 25, "days": 90}],
                                                        [{"kind": "payee_new", "min_seen": 3}]], judge=True, payee=None)
            assert not made.is_error
            got = money(await h.proposals.pending(h.alana, CONVERSATION, REMINDERS)).rule
            assert got.judge is True and got.payee is None
            assert got.clauses == ((payee("KVR"), above(25, 90)), (new_payer(3, 120),))
            await Talk(h).propose(11, payee="KVR")
            again = money(await h.proposals.pending(h.alana, CONVERSATION, REMINDERS)).rule
            assert again.judge is False and again.clauses == ()

    run(go())


NOT_RULES: list[dict[str, object]] = [
    {"payee": None}, {"conditions": [[{"kind": "sideways"}]]}, {"conditions": [[]]}, {"conditions": "KVR"},
    {"conditions": [[{"kind": "payee_new"}]] * 7}, {"direction": "sideways"}]


@pytest.mark.parametrize("bad", NOT_RULES)
def test_a_proposal_that_is_no_rule_is_an_error_and_stores_nothing(db_url: str, bad: dict[str, object]) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            assert (await Talk(h).propose(10, **bad)).is_error
            assert await h.proposals.pending(h.alana, CONVERSATION, REMINDERS) is None and await h.deposits.armed() == ()

    run(go())


def test_she_cannot_arm_in_the_turn_she_proposed_but_can_in_a_later_one_which_arms_what_she_proposed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            talk = Talk(h)
            await talk.propose(10, conditions=[[{"kind": "payee_new"}]], judge=True)
            same = await talk.arm(10)
            assert same.is_error and await h.deposits.armed() == ()
            assert await h.proposals.pending(h.alana, CONVERSATION, REMINDERS) is not None
            later = await talk.arm(11)
            assert not later.is_error
            (armed,) = await h.deposits.armed()
            assert armed.rule.clauses == ((new_payer(2, 120),),) and armed.rule.judge is True
            assert armed.rule.payee == "KVR" and str(armed.id) in later.content
            assert await h.proposals.pending(h.alana, CONVERSATION, REMINDERS) is None

    run(go())


def test_an_earlier_turn_cannot_arm_either_and_a_proposal_arms_once(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            talk = Talk(h)
            await talk.propose(10)
            assert (await talk.arm(9)).is_error and await h.deposits.armed() == ()
            assert not (await talk.arm(12)).is_error
            assert (await talk.arm(13)).is_error
            assert len(await h.deposits.armed()) == 1

    run(go())


def test_arming_with_nothing_proposed_in_this_conversation_by_this_person_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await Talk(h).propose(10)
            assert (await Talk(h, conversation=CONVERSATION + 1).arm(11)).is_error
            sam = person(db_url, h.home, "Sam")
            assert await h.proposals.pending(sam, CONVERSATION, REMINDERS) is None
            with pytest.raises(ProposalRefused) as e:
                await h.proposals.take(sam, CONVERSATION, REMINDERS, 11, TTL)
            assert e.value.reason == "none"
            assert await h.deposits.armed() == ()

    run(go())


def test_a_newer_proposal_replaces_the_older_ones_in_the_conversation_and_one_agreement_arms_one_rule(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            talk = Talk(h)
            await talk.propose(10, payee="First")
            await talk.propose(12, payee="Second")
            latest = await h.proposals.pending(h.alana, CONVERSATION, REMINDERS)
            assert latest is not None and money(latest).rule.payee == "Second" and latest.turn_id == 12
            assert (await talk.arm(12)).is_error        # not after the latest
            assert not (await talk.arm(13)).is_error
            (armed,) = await h.deposits.armed()
            assert armed.rule.payee == "Second"
            assert (await talk.arm(14)).is_error and len(await h.deposits.armed()) == 1

    run(go())


def test_conversations_and_people_keep_their_own_proposals(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            sam = person(db_url, h.home, "Sam")
            await Talk(h, CONVERSATION).propose(10, payee="Here")
            await Talk(h, CONVERSATION + 1).propose(10, payee="There")
            assert money(await h.proposals.pending(h.alana, CONVERSATION, REMINDERS)).rule.payee == "Here"
            assert money(await h.proposals.pending(h.alana, CONVERSATION + 1, REMINDERS)).rule.payee == "There"
            await h.proposals.propose(stored(h, DepositRule(CHECKING, "Checking", 5), CONVERSATION, 10, who=sam), TTL)
            assert money(await h.proposals.pending(h.alana, CONVERSATION, REMINDERS)).rule.payee == "Here"
            assert money(await h.proposals.pending(sam, CONVERSATION, REMINDERS)).rule.min_cents == 5

    run(go())


def test_a_proposal_older_than_the_ttl_is_expired_when_armed(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            rule = DepositRule(CHECKING, "Checking", 5)
            sent = stored(h, rule, 1, 10)
            await h.proposals.propose(sent, TTL)
            with pytest.raises(ProposalRefused) as e:
                await h.proposals.take(h.alana, 1, REMINDERS, 11, 0.0)
            assert e.value.reason == "expired" and await h.deposits.armed() == ()
            assert (await h.proposals.take(h.alana, 1, REMINDERS, 11, TTL)).payload == sent.payload
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None

    run(go())


def test_proposing_again_drops_proposals_older_than_the_ttl(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            rule = DepositRule(CHECKING, "Checking", 5)
            await h.proposals.propose(stored(h, rule, 1, 10), TTL)
            await h.proposals.propose(stored(h, rule, 2, 10), TTL)
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is not None
            await h.proposals.propose(stored(h, rule, 3, 10), 0.0)
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None and await h.proposals.pending(h.alana, 2, REMINDERS) is None

    run(go())


@pytest.mark.parametrize("turn,age_h,expected", [(11, 1, None), (11, 23, None), (11, 25, "expired"), (10, 1, "same_turn"),
                                                   (9, 1, "same_turn"), (50, 1, None), (50, 30, "expired")])
def test_refusal_is_by_turn_ids_and_the_age_of_the_proposal(turn: int, age_h: int, expected: str | None) -> None:
    p = Proposal(1, 1, 1, 10, NOW - timedelta(hours=age_h),
                 MoneyRule(Reminder(1, 1, 1, "b", NOW - timedelta(hours=age_h), None), DepositRule(CHECKING, "Checking", 5)))
    assert refusal(p, turn, NOW, TTL) == expected


def test_the_same_turn_is_refused_as_same_turn(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await h.proposals.propose(stored(h, DepositRule(CHECKING, "Checking", 5), 1, 10), TTL)
            with pytest.raises(ProposalRefused) as e:
                await h.proposals.take(h.alana, 1, REMINDERS, 10, TTL)
            assert e.value.reason == "same_turn"
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is not None

    run(go())


def test_a_proposal_is_not_a_rule_the_sense_fires_on(db_url: str) -> None:
    async def go() -> None:
        rows = [deposit("t1", "Bonus", 500_000, NOW.date(), merchant="KVR")]
        async with house(db_url, DepositSure(rows=rows)) as h:
            await Talk(h).propose(10)
            await deposit_sense.poll(NOW)
            assert await h.wakes.due(10) == ()

    run(go())


def test_she_is_offered_arming_only_in_a_turn_after_a_proposal_of_hers_in_the_conversation(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            talk = Talk(h)
            assert specs.ARM not in await talk.offered(10) and specs.ON_MONEY in await talk.offered(10)
            await talk.propose(10)
            assert specs.ARM not in await talk.offered(10)           # the turn she proposed it in
            assert specs.ARM not in await talk.offered(9)
            assert specs.ARM in await talk.offered(11)
            assert specs.ON_MONEY in await talk.offered(11)
            assert specs.ARM not in await Talk(h, CONVERSATION + 1).offered(11)
            assert specs.ARM not in await Talk(h, who=person(db_url, h.home, "Sam")).offered(11)
            await talk.arm(11)
            assert specs.ARM not in await talk.offered(12)

    run(go())


def test_the_guidance_for_arming_comes_with_the_tool_and_not_before(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            talk = Talk(h)
            await talk.propose(10)
            before = (await talk.say(10).catalogue()).instructions or ""
            after = (await talk.say(11).catalogue()).instructions or ""
            assert specs.ARM_INSTRUCTIONS not in before and specs.ARM_INSTRUCTIONS in after
            assert specs.ON_MONEY_INSTRUCTIONS in before and specs.ON_MONEY_INSTRUCTIONS in after

    run(go())


def test_the_arm_tool_takes_no_arguments_and_the_propose_tool_takes_conditions_and_judge(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            talk = Talk(h)
            await talk.propose(10)
            by = {s.name: s for s in (await talk.say(11).catalogue()).specs}
            arm: Mapping[str, Any] = by[specs.ARM].parameters
            assert not arm.get("properties") and not arm.get("required")
            put: Mapping[str, Any] = by[specs.ON_MONEY].parameters
            assert {"conditions", "judge"} <= set(put["properties"])
            assert specs.ON_MONEY in by and proposal_args()

    run(go())


def test_without_a_turn_she_proposes_nothing_and_is_offered_no_arming(db_url: str) -> None:
    async def go() -> None:
        async with house(db_url) as h:
            await Talk(h).propose(10)
            blind = ReminderTools(h.home, h.alana, private=True)
            assert specs.ARM not in [s.name for s in (await blind.catalogue()).specs]
            assert (await blind.call(ToolCall("p", specs.ON_MONEY, proposal_args()))).is_error
            assert (await blind.call(ToolCall("a", specs.ARM, {}))).is_error
            assert await h.deposits.armed() == ()

    run(go())
