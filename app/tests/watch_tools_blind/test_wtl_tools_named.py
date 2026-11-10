"""`watch`'s `tools`: only tools the speaker has in the turn can be named; naming one that acts proposes the watch
(`WatchSchedule`, in the REMINDERS topic) and `arm_reminder` arms it in a later person turn, as for a reminder."""

import asyncio

from watch_tools_blind_fakes import ALANA, CONVERSATION, KIND, TARGET, Shelf
from watch_tools_blind_support import (
    body,
    offered,
    plain,
    proposed_arm,
    refused,
    use,
    world,
)

from ashley.senses.proposal_payloads import REMINDERS


def test_naming_a_tool_that_only_reads_arms_at_once_with_that_tool() -> None:
    async def go() -> None:
        async with world() as w:
            result = body(await use(w.tools(), "watch", plain(tools=["look_up"])))
            assert w.store.armed[0].tools == ("look_up",) and w.proposals.proposed == []
            assert result.get("armed", True) is not False
    asyncio.run(go())


def test_naming_a_tool_that_acts_proposes_and_arms_nothing() -> None:
    async def go() -> None:
        async with world() as w:
            result = body(await use(w.tools(), "watch", plain(tools=["lamp_on"])))
            assert w.store.armed == []
            assert result["armed"] is False and result["tools"] == ["lamp_on"]
            (proposal,) = w.proposals.proposed
            assert (proposal.made_by, proposal.conversation_id, proposal.turn_id) == (ALANA, CONVERSATION, 10)
    asyncio.run(go())


def test_the_proposal_is_in_the_reminders_topic_and_carries_the_arm() -> None:
    async def go() -> None:
        async with world() as w:
            await use(w.tools(), "watch", plain(tools=["lamp_on"]))
            assert (await w.proposals.pending(ALANA, CONVERSATION, REMINDERS)) is not None
            arm = proposed_arm(w.proposals.proposed[0])
            assert (arm.kind, arm.target, arm.person_id, arm.tools) == (KIND, TARGET, ALANA, ("lamp_on",))
            body(await use(w.reminders(11), "arm_reminder"))
            assert w.store.armed[0].baseline[TARGET] == {"status": "working", "seq": 3}
    asyncio.run(go())


def test_a_mix_of_reading_and_acting_tools_is_proposed() -> None:
    async def go() -> None:
        async with world() as w:
            result = body(await use(w.tools(), "watch", plain(tools=["look_up", "lamp_on"])))
            assert result["armed"] is False and w.store.armed == []
    asyncio.run(go())


def test_arm_reminder_arms_the_proposed_watch_in_a_later_turn() -> None:
    async def go() -> None:
        async with world() as w:
            await use(w.tools(turn=(CONVERSATION, 10)), "watch", plain(tools=["lamp_on"]))
            assert "arm_reminder" in await offered(w.reminders(11))
            body(await use(w.reminders(11), "arm_reminder"))
            (arm,) = w.store.armed
            assert (arm.kind, arm.target, arm.person_id, arm.tools, arm.armed_by) == (
                KIND, TARGET, ALANA, ("lamp_on",), "ashley")
    asyncio.run(go())


def test_arm_reminder_in_the_proposing_turn_arms_nothing() -> None:
    async def go() -> None:
        async with world() as w:
            await use(w.tools(turn=(CONVERSATION, 10)), "watch", plain(tools=["lamp_on"]))
            assert "arm_reminder" not in await offered(w.reminders(10))
            refused(await use(w.reminders(10), "arm_reminder"))
            assert w.store.armed == []
    asyncio.run(go())


def test_a_proposed_watch_is_armed_once() -> None:
    async def go() -> None:
        async with world() as w:
            await use(w.tools(), "watch", plain(tools=["lamp_on"]))
            body(await use(w.reminders(11), "arm_reminder"))
            refused(await use(w.reminders(12), "arm_reminder"))
            assert len(w.store.armed) == 1
    asyncio.run(go())


def test_a_tool_the_speaker_does_not_have_cannot_be_named() -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(), "watch", plain(tools=["launch_rockets"])), "bad_arguments")
            refused(await use(w.tools(), "watch", plain(tools=["look_up", "launch_rockets"])), "bad_arguments")
            assert w.store.armed == [] and w.proposals.proposed == []
    asyncio.run(go())


def test_with_no_tools_in_the_turn_nothing_can_be_named() -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(shelf=Shelf()), "watch", plain(tools=["look_up"])), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())


def test_tools_is_a_list_of_names() -> None:
    async def go() -> None:
        async with world() as w:
            for bad in ("look_up", [5], [["look_up"]], {"look_up": 1}):
                refused(await use(w.tools(), "watch", plain(tools=bad)), "bad_arguments")
            assert w.store.armed == []
    asyncio.run(go())


def test_naming_a_tool_twice_names_it_once() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(tools=["look_up", "look_up"])))
            assert w.store.armed[0].tools == ("look_up",)
    asyncio.run(go())


def test_an_empty_list_names_no_tools() -> None:
    async def go() -> None:
        async with world() as w:
            body(await use(w.tools(), "watch", plain(tools=[])))
            assert not w.store.armed[0].tools and w.proposals.proposed == []
    asyncio.run(go())


def test_a_target_missing_from_the_read_is_refused_before_anything_is_proposed() -> None:
    async def go() -> None:
        from watch_tools_blind_fakes import without_target
        async with world(answer=without_target()) as w:
            refused(await use(w.tools(), "watch", plain(tools=["lamp_on"])), "not_found")
            assert w.proposals.proposed == []
    asyncio.run(go())


def test_proposing_needs_a_turn_to_propose_in() -> None:
    async def go() -> None:
        async with world() as w:
            refused(await use(w.tools(turn=None), "watch", plain(tools=["lamp_on"])))
            assert w.store.armed == [] and w.proposals.proposed == []
    asyncio.run(go())
