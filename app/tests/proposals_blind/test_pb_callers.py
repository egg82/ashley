"""What goes through the store from its callers: `remind` with a tool that acts and `house_change` of something
irreversible each store a proposal in their own topic and do nothing yet; `arm_reminder` and `house_confirm` agree from a
later person turn and consume only their own topic's; a newer proposal replaces the earlier in its topic."""

from datetime import UTC, datetime, timedelta

from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.proposal_payloads import HOUSE, REMINDERS, HouseChange, ReminderChange, ReminderSchedule
from ashley.tools.house_change import CHANGE, CONFIRM
from ashley.tools.tools import Tools
from contract.conversations_support import run
from proposals_blind_support import BRIEF, TTL, Shelf, World, house_change, proposal, tool_body, world

AT = f"{(datetime.now(UTC) + timedelta(days=30)).date().isoformat()}T10:30"


async def use(source: Tools, name: str, /, **args: object) -> ToolResult:
    return await source.call(ToolCall("c1", name, args))


async def offered(tools: Tools) -> set[str]:
    return {s.name for s in (await tools.catalogue()).specs}


async def remind(w: World, turn: int, brief: str = BRIEF, conversation: int = 1, who: int | None = None) -> ToolResult:
    got = await use(w.reminders(who, (conversation, turn), Shelf()), "remind", **{"for": "Alana", "at": AT, "what": brief, "tools": ["lamp_on"]})
    assert got.is_error is False
    return got


async def erase(w: World, turn: int, id_: str, conversation: int = 1) -> ToolResult:
    got = await use(w.changes(turn=(conversation, turn)), CHANGE, op="delete", kind="automation", id=id_)
    assert got.is_error is False
    return got


async def listed(w: World) -> list[str]:
    return [s.reminder.brief for s in await w.wakes.reminders(w.home, w.alana)]


def test_a_reminder_that_acts_is_stored_as_a_proposal_in_the_reminder_topic_and_not_scheduled(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await remind(w, 10, conversation=4)
            kept = await w.proposals.pending(w.alana, 4, REMINDERS)
            assert kept is not None and isinstance(kept.payload, ReminderSchedule)
            assert (kept.household_id, kept.made_by, kept.conversation_id, kept.turn_id) == (w.home, w.alana, 4, 10)
            assert kept.payload.reminder.brief == BRIEF and kept.payload.reminder.tools == ("lamp_on",)
            assert await w.proposals.pending(w.alana, 4, HOUSE) is None
            assert await listed(w) == []

    run(go())


def test_an_irreversible_house_change_is_stored_as_a_proposal_in_the_house_topic_and_not_carried_out(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await erase(w, 10, "porch", conversation=4)
            kept = await w.proposals.pending(w.alana, 4, HOUSE)
            assert kept is not None and isinstance(kept.payload, HouseChange)
            assert (kept.payload.change.op, kept.payload.change.kind, kept.payload.change.id) == ("delete", "automation", "porch")
            assert (kept.household_id, kept.made_by, kept.conversation_id, kept.turn_id) == (w.home, w.alana, 4, 10)
            assert kept.payload.summary.strip()
            assert await w.proposals.pending(w.alana, 4, REMINDERS) is None
            assert w.house.calls == []

    run(go())


def test_a_house_change_and_a_reminder_proposed_in_one_conversation_are_agreed_apart(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await remind(w, 10)
            await erase(w, 10, "porch")
            assert await w.proposals.pending(w.alana, 1, REMINDERS) is not None
            assert await w.proposals.pending(w.alana, 1, HOUSE) is not None
            armed = await use(w.reminders(None, (1, 11), Shelf()), "arm_reminder")
            assert armed.is_error is False and await listed(w) == [BRIEF]
            made = (await w.wakes.reminders(w.home, w.alana))[0].reminder
            assert made.tools == ("lamp_on",) and made.route == "phone"
            assert await w.proposals.pending(w.alana, 1, REMINDERS) is None
            assert await w.proposals.pending(w.alana, 1, HOUSE) is not None and w.house.calls == []
            done = await use(w.changes(turn=(1, 12)), CONFIRM)
            assert done.is_error is False and w.house.calls == [("delete_config", ("automation", "porch"))]
            assert await w.proposals.pending(w.alana, 1, HOUSE) is None
            assert await listed(w) == [BRIEF]

    run(go())


def test_confirming_the_house_first_leaves_the_reminder_to_be_armed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await remind(w, 10)
            await erase(w, 10, "porch")
            assert (await use(w.changes(turn=(1, 11)), CONFIRM)).is_error is False
            assert await w.proposals.pending(w.alana, 1, REMINDERS) is not None and await listed(w) == []
            assert (await use(w.reminders(None, (1, 12), Shelf()), "arm_reminder")).is_error is False
            assert await listed(w) == [BRIEF]

    run(go())


def test_a_newer_reminder_proposal_replaces_the_earlier_so_one_agreement_arms_one(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await remind(w, 10, "first")
            await remind(w, 12, "second")
            kept = await w.proposals.pending(w.alana, 1, REMINDERS)
            assert kept is not None and isinstance(kept.payload, ReminderSchedule) and kept.payload.reminder.brief == "second"
            assert (await use(w.reminders(None, (1, 13), Shelf()), "arm_reminder")).is_error is False
            assert await listed(w) == ["second"]
            assert (await use(w.reminders(None, (1, 14), Shelf()), "arm_reminder")).is_error is True
            assert await listed(w) == ["second"]

    run(go())


def test_a_newer_house_proposal_replaces_the_earlier_so_only_it_is_carried_out(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await erase(w, 10, "first")
            await erase(w, 12, "second")
            assert (await use(w.changes(turn=(1, 13)), CONFIRM)).is_error is False
            assert w.house.calls == [("delete_config", ("automation", "second"))]
            assert CONFIRM not in await offered(w.changes(turn=(1, 14)))
            assert (await use(w.changes(turn=(1, 14)), CONFIRM)).is_error is True
            assert w.house.calls == [("delete_config", ("automation", "second"))]

    run(go())


def test_the_turn_that_proposes_cannot_agree_and_a_later_one_can(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await erase(w, 10, "porch")
            assert CONFIRM not in await offered(w.changes(turn=(1, 10)))
            assert (await use(w.changes(turn=(1, 10)), CONFIRM)).is_error is True and w.house.calls == []
            assert await w.proposals.pending(w.alana, 1, HOUSE) is not None
            assert CONFIRM in await offered(w.changes(turn=(1, 11)))

    run(go())


def test_another_person_or_another_conversation_cannot_agree(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await erase(w, 10, "porch")
            for tools in (w.changes(w.sam, (1, 11)), w.changes(turn=(2, 11))):
                assert CONFIRM not in await offered(tools)
                assert (await use(tools, CONFIRM)).is_error is True
            assert w.house.calls == [] and await w.proposals.pending(w.alana, 1, HOUSE) is not None

    run(go())


def test_a_proposal_older_than_the_limit_is_not_carried_out(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await w.proposals.propose(proposal(house_change("old", "porch"), w.home, w.alana, 1, 10,
                                               datetime.now(UTC) - timedelta(days=2)), 3 * 86400.0)
            late = w.changes(turn=(1, 11), ttl_s=TTL)
            assert (await use(late, CONFIRM)).is_error is True
            assert w.house.calls == []

    run(go())


def test_arm_reminder_is_offered_only_in_a_later_turn_of_the_conversation_after_a_reminder_proposal(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            assert "arm_reminder" not in await offered(w.reminders(None, (1, 11), Shelf()))
            await remind(w, 10)
            assert "arm_reminder" not in await offered(w.reminders(None, (1, 10), Shelf()))
            assert "arm_reminder" in await offered(w.reminders(None, (1, 11), Shelf()))
            assert "arm_reminder" not in await offered(w.reminders(None, (2, 11), Shelf()))
            assert "arm_reminder" not in await offered(w.reminders(w.sam, (1, 11), Shelf()))

    run(go())


def test_a_house_proposal_alone_does_not_offer_arm_reminder_nor_a_reminder_proposal_house_confirm(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            await erase(w, 10, "porch")
            assert "arm_reminder" not in await offered(w.reminders(None, (1, 11), Shelf()))
            await remind(w, 12, conversation=2)
            assert CONFIRM not in await offered(w.changes(turn=(2, 13)))

    run(go())


def test_giving_a_reminder_an_acting_tool_proposes_the_change_and_arming_makes_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            made = await use(w.reminders(None, (1, 9), Shelf()), "remind", **{"for": "Alana", "at": AT, "what": BRIEF})
            wake = tool_body(made)["id"]
            asked = await use(w.reminders(None, (1, 10), Shelf()), "change_reminder", id=wake, tools=["lamp_on"])
            assert asked.is_error is False
            kept = await w.proposals.pending(w.alana, 1, REMINDERS)
            assert kept is not None and isinstance(kept.payload, ReminderChange) and kept.payload.target == wake
            assert kept.payload.reminder.tools == ("lamp_on",)
            assert [s.reminder.tools for s in await w.wakes.reminders(w.home, w.alana)] != [("lamp_on",)]
            assert (await use(w.reminders(None, (1, 11), Shelf()), "arm_reminder")).is_error is False
            assert [s.reminder.tools for s in await w.wakes.reminders(w.home, w.alana)] == [("lamp_on",)]
            assert await w.proposals.pending(w.alana, 1, REMINDERS) is None

    run(go())
