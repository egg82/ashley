"""`ReminderTools`: remind, change_reminder and arm_reminder by fields. A reminder that acts is proposed and set only by
`arm_reminder` in a later turn of the same person's conversation; that tool is offered only after a proposal of theirs,
and a newer proposal replaces an older. One that only reads, and an edit that adds nothing acting, take effect at once."""

from datetime import UTC, datetime

import pytest
from ashley.senses.proposal_payloads import REMINDERS, MoneyRule
from ashley.senses.proposals import Proposal
from contract.conversations_support import run, scalar
from rsh_support import ACT, AT, BRIEF, DENVER, READ, RULE, Shelf, body, home, offered, proposed, remind_args, stored, use


def test_arm_reminder_is_offered_only_in_a_turn_after_a_proposal_of_theirs_in_that_conversation(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 10), shelf=shelf))
            await proposed(h, shelf, 10)
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 10), shelf=shelf))
            assert "arm_reminder" in await offered(h.tools(turn=(1, 11), shelf=shelf))
            assert "arm_reminder" in await offered(h.tools(turn=(1, 99), shelf=shelf))
            assert "arm_reminder" not in await offered(h.tools(turn=(2, 11), shelf=shelf))
            assert "arm_reminder" not in await offered(h.tools(speaker=h.sam, turn=(1, 11), shelf=shelf))
            assert "arm_reminder" not in await offered(h.tools(turn=None, shelf=shelf))

    run(go())


def test_arm_reminder_is_no_longer_offered_once_the_proposal_is_armed(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            await proposed(h, shelf, 10, tools=["lamp_on"])
            assert (await use(h.tools(turn=(1, 11), shelf=shelf), "arm_reminder")).is_error is False
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 12), shelf=shelf))
            second = await use(h.tools(turn=(1, 12), shelf=shelf), "arm_reminder")
            assert second.is_error is True
            assert len(await stored(h)) == 1

    run(go())


def test_a_reminder_that_acts_is_stored_only_when_armed_in_a_later_turn(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            first = await use(h.tools(turn=(1, 10), shelf=shelf), "remind", remind_args(tools=["lamp_on"], delivery="quiet"))
            assert first.is_error is False and body(first)["armed"] is False and "id" not in body(first)
            assert await stored(h) == []
            same_turn = await use(h.tools(turn=(1, 10), shelf=shelf), "arm_reminder")
            assert same_turn.is_error is True
            assert await stored(h) == []
            armed = await use(h.tools(turn=(1, 11), shelf=shelf), "arm_reminder")
            assert armed.is_error is False
            (got,) = await stored(h)
            r = got.reminder
            assert (r.tools, r.route, r.brief, r.person_id, r.made_by) == (("lamp_on",), "quiet", BRIEF, h.alana, h.alana)
            assert r.due_at.astimezone(DENVER).strftime("%Y-%m-%dT%H:%M") == AT
            assert shelf.called == []

    run(go())


def test_a_newer_proposal_replaces_the_older_so_one_agreement_arms_one_reminder(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            await proposed(h, shelf, 10, tools=["lamp_on"], what="FIRST ask")
            await proposed(h, shelf, 10, tools=["lamp_on"], what="SECOND ask")
            assert (await use(h.tools(turn=(1, 11), shelf=shelf), "arm_reminder")).is_error is False
            assert [s.reminder.brief for s in await stored(h)] == ["SECOND ask"]
            assert (await use(h.tools(turn=(1, 12), shelf=shelf), "arm_reminder")).is_error is True
            assert len(await stored(h)) == 1

    run(go())


def test_proposing_again_in_the_turn_that_should_have_agreed_replaces_and_arms_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            await proposed(h, shelf, 10, tools=["lamp_on"], what="ASKED")
            await proposed(h, shelf, 11, tools=["lamp_on"], what="ASKED AGAIN")
            assert await stored(h) == []
            assert (await use(h.tools(turn=(1, 11), shelf=shelf), "arm_reminder")).is_error is True
            assert await stored(h) == []
            assert (await use(h.tools(turn=(1, 12), shelf=shelf), "arm_reminder")).is_error is False
            assert [s.reminder.brief for s in await stored(h)] == ["ASKED AGAIN"]

    run(go())


def test_a_proposal_in_another_conversation_is_not_armed_from_this_one(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            await proposed(h, shelf, 10, conv=1, tools=["lamp_on"])
            assert (await use(h.tools(turn=(2, 11), shelf=shelf), "arm_reminder")).is_error is True
            assert await stored(h) == []

    run(go())


def test_a_reminder_that_only_reads_is_set_at_once_with_its_tools_and_needs_no_arming(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            result = await use(h.tools(turn=(1, 10), shelf=shelf), "remind", remind_args(tools=["look_up"]))
            assert result.is_error is False and isinstance(body(result)["id"], int)
            (got,) = await stored(h)
            assert got.reminder.tools == ("look_up",) and got.id == body(result)["id"]
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 11), shelf=shelf))

    run(go())


def test_a_reminder_naming_no_tools_is_set_at_once_with_none(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            result = await use(h.tools(turn=(1, 10), shelf=Shelf(READ, ACT)), "remind", remind_args())
            assert result.is_error is False
            (got,) = await stored(h)
            assert (got.reminder.tools, got.reminder.route) == (None, "phone")

    run(go())


@pytest.mark.parametrize("names", [["hacking"], ["remind"], ["lamp_on", "nope"], ["arm_reminder"]])
def test_a_tool_she_does_not_have_in_the_turn_is_refused_and_nothing_is_proposed_or_set(db_url: str, names: list[str]) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            result = await use(h.tools(turn=(1, 10), shelf=shelf), "remind", remind_args(tools=names))
            assert result.is_error is True
            assert await stored(h) == []
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None

    run(go())


@pytest.mark.parametrize("tools", [["look_up"], ["lamp_on"]])
def test_tools_cannot_be_named_in_a_turn_that_does_not_reach_the_speaker_alone(db_url: str, tools: list[str]) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            t = h.tools(turn=(1, 10), shelf=shelf, private=False)
            result = await use(t, "remind", remind_args(tools=tools))
            assert result.is_error is True or all(s.reminder.tools is None for s in await stored(h))
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 11), shelf=shelf, private=False))

    run(go())


def test_a_reminder_that_acts_for_another_person_is_refused_and_proposes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            result = await use(h.tools(turn=(1, 10), shelf=shelf), "remind", remind_args(**{"for": "Sam"}, tools=["lamp_on"]))
            assert result.is_error is True
            assert await h.proposals.pending(h.alana, 1, REMINDERS) is None and await stored(h, h.sam) == []
            assert "arm_reminder" not in await offered(h.tools(turn=(1, 11), shelf=shelf))

    run(go())


def test_a_reminder_that_reads_may_be_set_for_another_person(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            result = await use(h.tools(turn=(1, 10), shelf=Shelf(READ, ACT)), "remind", remind_args(**{"for": "Sam"}, tools=["look_up"]))
            assert result.is_error is False
            (got,) = await stored(h, h.sam)
            assert (got.reminder.person_id, got.reminder.made_by, got.reminder.tools) == (h.sam, h.alana, ("look_up",))

    run(go())


def test_agreeing_to_a_money_reminder_arms_it_with_the_route_and_tools_proposed(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            reminder = h.reminder(route="quiet", tools=("lamp_on",))
            await h.proposals.propose(Proposal(h.house, reminder.made_by, 1, 10, datetime.now(UTC), MoneyRule(reminder, RULE)), 3600.0)
            armed = await use(h.tools(turn=(1, 11), shelf=Shelf(READ, ACT)), "arm_reminder")
            assert armed.is_error is False
            (got,) = await stored(h)
            assert (got.deposit, got.reminder.route, got.reminder.tools) == (RULE, "quiet", ("lamp_on",))

    run(go())


def test_proposing_a_reminder_that_acts_drops_proposals_older_than_the_ttl_and_keeps_the_younger(db_url: str) -> None:
    async def go() -> None:
        async with home(db_url) as h:
            shelf = Shelf(READ, ACT)
            for conversation in (1, 2):
                await use(h.tools(turn=(conversation, 10), shelf=shelf), "remind", remind_args(tools=["lamp_on"]))
            scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = now() - interval '36 hours' "
                           "WHERE conversation_id = 1 RETURNING 1) SELECT count(*) FROM u")
            scalar(db_url, "WITH u AS (UPDATE proposals SET created_at = now() - interval '12 hours' "
                           "WHERE conversation_id = 2 RETURNING 1) SELECT count(*) FROM u")
            await use(h.tools(turn=(3, 10), shelf=shelf), "remind", remind_args(tools=["lamp_on"]))
            assert scalar(db_url, "SELECT array_agg(conversation_id ORDER BY conversation_id) FROM proposals") == [2, 3]

    run(go())
