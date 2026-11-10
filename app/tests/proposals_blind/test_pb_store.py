"""`Proposals.propose`, `pending` and `take` on the Postgres store: what is stored comes back as it was given, a person has
one pending proposal per conversation and topic and a new one replaces the earlier, topics never touch each other, and a
payload the payload module refuses replaces nothing."""

from datetime import timedelta

import pytest
from ashley.senses.proposal_payloads import HOUSE, MAX_BRIEF, MAX_TOOLS, REMINDERS, Payload, Topic
from ashley.senses.proposals import ProposalRefused
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from contract.conversations_support import run
from proposals_blind_support import BRIEF, TTL, Store, clock, edit, house_change, money, proposal, reminder, schedule, store
from ashley.senses.proposal_payloads import MoneyRule, ReminderSchedule
from ashley.senses.proposals import Proposals


async def round_trip[P: Payload](s: Store, payload: P, topic: Topic[P]) -> None:
    made = proposal(payload, s.house, s.alana, 31, 8, clock() - timedelta(seconds=30))
    pid = await s.store.propose(made, TTL)
    assert isinstance(pid, int)
    assert await s.store.pending(s.alana, 31, topic) == made
    assert await s.store.take(s.alana, 31, topic, 9, TTL) == made


def test_what_is_proposed_comes_back_whole_from_pending_and_from_take(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await round_trip(s, schedule(s.house, s.alana), REMINDERS)
            await round_trip(s, money(s.house, s.alana), REMINDERS)
            await round_trip(s, edit(s.house, s.alana), REMINDERS)
            await round_trip(s, house_change(), HOUSE)

    run(go())


def test_pending_reads_without_consuming_and_take_consumes(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            made = proposal(schedule(s.house, s.alana), s.house, s.alana)
            await s.store.propose(made, TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == made
            assert await s.store.pending(s.alana, 1, REMINDERS) == made
            assert await s.store.take(s.alana, 1, REMINDERS, 11, TTL) == made
            assert await s.store.pending(s.alana, 1, REMINDERS) is None
            with pytest.raises(ProposalRefused) as gone:
                await s.store.take(s.alana, 1, REMINDERS, 12, TTL)
            assert gone.value.reason == "none"

    run(go())


def test_nothing_pending_is_none_and_taking_it_is_refused_none(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            assert await s.store.pending(s.alana, 1, REMINDERS) is None
            assert await s.store.pending(s.alana, 1, HOUSE) is None
            with pytest.raises(ProposalRefused) as gone:
                await s.store.take(s.alana, 1, HOUSE, 11, TTL)
            assert gone.value.reason == "none"

    run(go())


def test_each_propose_gets_its_own_id(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            first = await s.store.propose(proposal(schedule(s.house, s.alana), s.house, s.alana), TTL)
            second = await s.store.propose(proposal(schedule(s.house, s.alana), s.house, s.alana), TTL)
            other = await s.store.propose(proposal(schedule(s.house, s.sam), s.house, s.sam), TTL)
            assert len({first, second, other}) == 3

    run(go())


def test_a_new_proposal_replaces_the_earlier_of_its_person_conversation_and_topic(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await s.store.propose(proposal(schedule(s.house, s.alana, "first"), s.house, s.alana, turn=10), TTL)
            second = proposal(schedule(s.house, s.alana, "second"), s.house, s.alana, turn=12)
            await s.store.propose(second, TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == second
            assert await s.store.take(s.alana, 1, REMINDERS, 13, TTL) == second
            with pytest.raises(ProposalRefused) as gone:
                await s.store.take(s.alana, 1, REMINDERS, 14, TTL)
            assert gone.value.reason == "none"

    run(go())


def test_one_topic_family_replaces_across_payload_kinds(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await s.store.propose(proposal(schedule(s.house, s.alana), s.house, s.alana, turn=10), TTL)
            await s.store.propose(proposal(money(s.house, s.alana), s.house, s.alana, turn=11), TTL)
            got = await s.store.pending(s.alana, 1, REMINDERS)
            assert got is not None and isinstance(got.payload, MoneyRule)
            await s.store.propose(proposal(edit(s.house, s.alana), s.house, s.alana, turn=12), TTL)
            got = await s.store.pending(s.alana, 1, REMINDERS)
            assert got is not None and got.turn_id == 12 and not isinstance(got.payload, (MoneyRule, ReminderSchedule))

    run(go())


def test_topics_replace_only_themselves(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            remind = proposal(schedule(s.house, s.alana), s.house, s.alana, turn=10)
            change = proposal(house_change(), s.house, s.alana, turn=10)
            await s.store.propose(remind, TTL)
            await s.store.propose(change, TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == remind
            assert await s.store.pending(s.alana, 1, HOUSE) == change
            assert await s.store.take(s.alana, 1, HOUSE, 11, TTL) == change
            assert await s.store.pending(s.alana, 1, REMINDERS) == remind
            assert await s.store.take(s.alana, 1, REMINDERS, 11, TTL) == remind

    run(go())


def test_taking_one_topic_never_takes_the_other(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await s.store.propose(proposal(house_change(), s.house, s.alana, turn=10), TTL)
            with pytest.raises(ProposalRefused) as wrong:
                await s.store.take(s.alana, 1, REMINDERS, 11, TTL)
            assert wrong.value.reason == "none"
            assert await s.store.pending(s.alana, 1, HOUSE) is not None

    run(go())


def test_people_and_conversations_each_keep_their_own_proposal(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            mine = proposal(schedule(s.house, s.alana, "mine"), s.house, s.alana, 1, 10)
            there = proposal(schedule(s.house, s.alana, "there"), s.house, s.alana, 2, 10)
            theirs = proposal(schedule(s.house, s.sam, "theirs"), s.house, s.sam, 1, 10)
            kims = proposal(schedule(s.other_house, s.kim, "kims"), s.other_house, s.kim, 1, 10)
            for made in (mine, there, theirs, kims):
                await s.store.propose(made, TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == mine
            assert await s.store.pending(s.alana, 2, REMINDERS) == there
            assert await s.store.pending(s.sam, 1, REMINDERS) == theirs
            assert await s.store.pending(s.kim, 1, REMINDERS) == kims
            assert await s.store.pending(s.sam, 2, REMINDERS) is None
            assert await s.store.take(s.sam, 1, REMINDERS, 11, TTL) == theirs
            assert await s.store.pending(s.alana, 1, REMINDERS) == mine

    run(go())


def test_a_person_cannot_take_what_was_proposed_to_another_or_in_another_conversation(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            await s.store.propose(proposal(schedule(s.house, s.alana), s.house, s.alana, 1, 10), TTL)
            for who, conversation in ((s.sam, 1), (s.alana, 2)):
                with pytest.raises(ProposalRefused) as gone:
                    await s.store.take(who, conversation, REMINDERS, 11, TTL)
                assert gone.value.reason == "none"
            assert await s.store.pending(s.alana, 1, REMINDERS) is not None

    run(go())


def test_proposed_at_is_stored_as_given(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            at = clock() - timedelta(seconds=123, microseconds=456)
            await s.store.propose(proposal(house_change(), s.house, s.alana, at=at), TTL)
            got = await s.store.pending(s.alana, 1, HOUSE)
            assert got is not None and got.proposed_at == at

    run(go())


@pytest.mark.parametrize("brief,tool_count", [("", 0), ("x" * (MAX_BRIEF + 1), 0), ("bad\x00brief", 0), (BRIEF, MAX_TOOLS + 1)])
def test_a_reminder_the_payload_module_refuses_raises_value_error_and_replaces_nothing(db_url: str, brief: str, tool_count: int) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            kept = proposal(schedule(s.house, s.alana), s.house, s.alana)
            await s.store.propose(kept, TTL)
            bad = reminder(s.house, s.alana, brief, tools=tuple(f"t{i}" for i in range(tool_count)) or None)
            with pytest.raises(ValueError):
                await s.store.propose(proposal(ReminderSchedule(bad), s.house, s.alana, turn=20), TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == kept

    run(go())


def test_a_reminder_at_the_limits_is_stored(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            edge = proposal(ReminderSchedule(reminder(s.house, s.alana, "x" * MAX_BRIEF, tools=tuple(f"t{i}" for i in range(MAX_TOOLS)))),
                            s.house, s.alana)
            await s.store.propose(edge, TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == edge
            one = proposal(ReminderSchedule(reminder(s.house, s.alana, "x")), s.house, s.alana, turn=11)
            await s.store.propose(one, TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == one

    run(go())


def test_a_money_rule_that_repeats_raises_value_error_and_replaces_nothing(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            kept = proposal(money(s.house, s.alana), s.house, s.alana)
            await s.store.propose(kept, TTL)
            weekly = Repeat("weekly", 1, clock().replace(tzinfo=None))
            repeating = MoneyRule(Reminder(s.house, s.alana, s.alana, BRIEF, clock(), weekly), money(s.house, s.alana).rule)
            with pytest.raises(ValueError):
                await s.store.propose(proposal(repeating, s.house, s.alana, turn=20), TTL)
            assert await s.store.pending(s.alana, 1, REMINDERS) == kept

    run(go())


def test_propose_drops_the_older_than_ttl_proposals_of_its_own_topic_only(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            old = clock() - timedelta(hours=2)
            await s.store.propose(proposal(schedule(s.house, s.sam), s.house, s.sam, 5, at=old), 7200 * 3)
            await s.store.propose(proposal(schedule(s.house, s.alana), s.house, s.alana, 6, at=old), 7200 * 3)
            await s.store.propose(proposal(house_change(), s.house, s.sam, 5, at=old), 7200 * 3)
            await s.store.propose(proposal(schedule(s.house, s.alana), s.house, s.alana, 1), TTL)
            assert await s.store.pending(s.sam, 5, REMINDERS) is None
            assert await s.store.pending(s.alana, 6, REMINDERS) is None
            assert await s.store.pending(s.sam, 5, HOUSE) is not None
            assert await s.store.pending(s.alana, 1, REMINDERS) is not None

    run(go())


def test_propose_keeps_the_proposals_still_within_ttl(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            recent = clock() - timedelta(seconds=60)
            kept = proposal(schedule(s.house, s.sam), s.house, s.sam, 5, at=recent)
            await s.store.propose(kept, TTL)
            await s.store.propose(proposal(schedule(s.house, s.alana), s.house, s.alana, 1), TTL)
            assert await s.store.pending(s.sam, 5, REMINDERS) == kept

    run(go())


def test_the_house_topic_purges_only_house_proposals(db_url: str) -> None:
    async def go() -> None:
        async with store(db_url) as s:
            old = clock() - timedelta(hours=2)
            await s.store.propose(proposal(schedule(s.house, s.sam), s.house, s.sam, 5, at=old), 7200 * 3)
            await s.store.propose(proposal(house_change(), s.house, s.sam, 5, at=old), 7200 * 3)
            await s.store.propose(proposal(house_change(), s.house, s.alana, 1), TTL)
            assert await s.store.pending(s.sam, 5, HOUSE) is None
            assert await s.store.pending(s.sam, 5, REMINDERS) is not None

    run(go())


def test_an_unwired_process_gets_a_store_that_raises(db_url: str) -> None:
    from ashley import services

    async def go() -> None:
        unwired = services.get(Proposals)
        with pytest.raises(Exception):
            await unwired.pending(1, 1, REMINDERS)
        with pytest.raises(Exception):
            await unwired.take(1, 1, REMINDERS, 2, TTL)
        with pytest.raises(Exception):
            await unwired.propose(proposal(house_change(), 1, 1), TTL)

    run(go())
