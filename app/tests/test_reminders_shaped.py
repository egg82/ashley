"""Reminders she shapes, over a real database: a reminder carries where its words go and the tools its turn may use, a
repeat takes weekdays and an end, and a reminder is edited with its id kept. A reminder that acts is proposed and set
only after the person agrees in a later turn, as a money rule is."""

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from ashley import services
from ashley.channels import turn_tools
from ashley.channels.model import Inbound
from ashley.channels.wake import reminder_turn, runner
from ashley.inference.model import ToolCall, ToolCalls, ToolResult
from ashley.people.model import Person
from ashley.db.pool import PoolDatabase
from ashley.senses.deposit_rule import DepositRule
from ashley.senses.deposits import Deposits
from ashley.senses.postgres_deposits import PostgresDeposits
from ashley.senses.postgres_proposals import PostgresProposals
from ashley.senses.proposal_payloads import MoneyRule, ReminderChange, ReminderSchedule
from ashley.senses.proposals import Proposal, Proposals, refusal
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from ashley.tools.reminders import ReminderTools
from ashley.tools.tools import Tools
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import person, run, scalar
from test_reminder_turn import BRIEF, SAYS, World, world
from wake_support import Switchboard

DENVER = ZoneInfo("America/Denver")
ACT = ("switch", "look")
SOON = datetime.now(UTC) + timedelta(days=2)


def switch_it() -> ToolCalls:
    return ToolCalls((ToolCall("c1", "switch", {}),))


def tools_for(w: World, who: int | None = None, turn: int = 5, conversation: int = 1,
              board: Tools | None = None) -> ReminderTools:
    kept = board or Switchboard()
    return ReminderTools(w.home, who or w.alana, private=True, turn=(conversation, turn), usable=lambda: kept)


async def call(tools: ReminderTools, name: str, args: dict[str, object]) -> ToolResult:
    return await tools.call(ToolCall("c", name, args))


def body(result: ToolResult) -> dict[str, object]:
    assert not result.is_error, result.content
    return json.loads(result.content)


def tomorrow_at(hour: int) -> str:
    return (datetime.now(DENVER) + timedelta(days=1)).strftime(f"%Y-%m-%dT{hour:02d}:00")


def test_the_fired_turn_offers_the_reads_unless_the_reminder_names_its_tools() -> None:
    plain = Reminder(1, 2, 3, BRIEF, SOON, None)
    acting = Reminder(1, 2, 3, BRIEF, SOON, None, None, "quiet", ACT)
    a, b = Person(2, 1, "Sam"), Person(3, 1, "Alana")
    quiet, acts = reminder_turn.inbound(7, plain, a, b), reminder_turn.inbound(7, acting, a, b)
    assert quiet.reads_only and quiet.tools_only is None
    assert acts.tools_only == ACT and not acts.reads_only and acts.promised and acts.thread == "push:2"
    assert reminder_turn.said(plain, a, b) != reminder_turn.said(acting, a, b)


def test_a_reminder_with_tools_acts_when_it_falls_due_and_one_without_cannot(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            board = Switchboard()
            services.register(Tools, board)
            now = datetime.now(UTC) - timedelta(seconds=1)
            await w.wakes.schedule(Reminder(w.home, w.alana, w.alana, "turn the porch light off", now, None, None,
                                            "phone", ("switch",)))
            w.model.script = [switch_it(), SAYS]
            await runner.sweep()
            assert [c.name for c in board.ran] == ["switch"]
            board.ran.clear()
            await w.wakes.schedule(Reminder(w.home, w.alana, w.alana, BRIEF, now, None))
            w.model.script = [switch_it(), SAYS]
            await runner.sweep()
            assert board.ran == []
    run(go())


def test_a_reminder_with_tools_offers_only_the_tools_it_names() -> None:
    inbound = reminder_turn.inbound(1, Reminder(1, 2, 2, BRIEF, SOON, None, None, "phone", ("look",)),
                                    Person(2, 1, "Sam"), Person(2, 1, "Sam"))
    assert isinstance(inbound, Inbound) and inbound.tools_only == ("look",)
    assert turn_tools.for_turn(inbound) is not None


def test_a_quiet_reminder_fires_and_stores_her_answer_but_is_never_pushed_or_listed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            made = await w.wakes.schedule(Reminder(w.home, w.alana, w.alana, BRIEF,
                                                   datetime.now(UTC) - timedelta(seconds=1), None, None, "quiet"))
            w.model.script = [SAYS]
            await runner.sweep()
            assert w.outcome(made) == "turn" and w.answers() == [(f"push:{w.alana}", SAYS.text)]
            assert await w.wakes.undelivered(10, 0, 3600) == () and await w.wakes.reminders(w.home, w.alana) == ()
            assert scalar(db_url, "SELECT delivery FROM wakes WHERE id = %s", (made,)) is None
    run(go())


def test_a_fired_phone_reminder_is_still_waiting_for_its_push(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            made = await w.wakes.schedule(Reminder(w.home, w.alana, w.alana, BRIEF,
                                                   datetime.now(UTC) - timedelta(seconds=1), None))
            w.model.script = [SAYS]
            await runner.sweep()
            assert [d.id for d in await w.wakes.undelivered(10, 0, 3600)] == [made]
    run(go())


def test_the_next_occurrence_carries_the_route_and_tools_and_the_series_ends_at_its_end_date(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            week = datetime.now(DENVER).replace(tzinfo=None) - timedelta(days=7)
            ends = (datetime.now(DENVER) + timedelta(days=3)).date()
            repeat = Repeat("daily", 1, week.replace(minute=0, second=0, microsecond=0), until=ends)
            await w.wakes.schedule(Reminder(w.home, w.alana, w.alana, BRIEF, datetime.now(UTC) - timedelta(seconds=1),
                                            repeat, None, "quiet", ("look",)))
            w.model.script = [SAYS]
            await runner.sweep()
            [(nxt, _)] = w.waiting()
            assert scalar(db_url, "SELECT json_build_array(route, tools) FROM wakes WHERE id = %s", (nxt,)) == [
                "quiet", ["look"]]
            scalar(db_url, "UPDATE wakes SET due_at = now() - interval '1 second', "
                           "repeat = jsonb_set(repeat, '{until}', to_jsonb(%s::text)) WHERE id = %s RETURNING id",
                   (datetime.now(DENVER).date().isoformat(), nxt))
            w.model.script = [SAYS]
            await runner.sweep()
            assert w.waiting() == []
    run(go())


def test_an_edit_keeps_the_id_and_the_fired_ones_and_changes_only_what_is_given(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            due = SOON
            made = await w.wakes.schedule(Reminder(w.home, w.sam, w.alana, "water the plants", due, None))
            later = due + timedelta(hours=3)
            ok = await w.wakes.edit(w.home, w.sam, made, Reminder(w.home, w.sam, w.alana, "water the ferns", later,
                                                                  Repeat("daily", 1, later.replace(tzinfo=None)),
                                                                  None, "quiet", ("look",)))
            [got] = await w.wakes.reminders(w.home, w.alana)
            assert ok and got.id == made and got.reminder.brief == "water the ferns" and got.reminder.due_at == later
            assert got.reminder.route == "quiet" and got.reminder.tools == ("look",) and got.reminder.repeat is not None
            assert (got.reminder.person_id, got.reminder.made_by) == (w.sam, w.alana)
            other = person(db_url, w.home, "Pat")
            assert not await w.wakes.edit(w.home, other, made, got.reminder)
            assert not await w.wakes.edit(w.home, w.alana, made + 100, got.reminder)
            await w.wakes.cancel(w.home, w.alana, made)
            assert not await w.wakes.edit(w.home, w.alana, made, got.reminder)
    run(go())


def test_editing_a_reminder_that_waits_on_money_changes_what_it_says_but_never_its_time(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            db = PoolDatabase(db_url, connect_timeout_s=5.0)
            await db.open()
            try:
                deposits = PostgresDeposits(db)
                services.register(Deposits, deposits)
                set_at = datetime.now(UTC)
                armed = await deposits.arm(Reminder(w.home, w.alana, w.alana, "move it", set_at, None),
                                           DepositRule("a", "A", 1))
                changed = Reminder(w.home, w.alana, w.alana, "move all of it", set_at + timedelta(days=9),
                                   Repeat("daily", 1, SOON.replace(tzinfo=None)), None, "quiet", ("look",))
                assert await w.wakes.edit(w.home, w.alana, armed, changed)
                (row,) = [r for r in await deposits.armed() if r.id == armed]
                assert row.armed_at == set_at
                assert scalar(db_url, "SELECT json_build_array(brief, route, tools, repeat IS NULL) FROM wakes "
                                      "WHERE id = %s", (armed,)) == ["move all of it", "quiet", ["look"], True]
            finally:
                services.unregister(Deposits)
                await db.close()
    run(go())


def test_a_reminder_that_acts_is_only_proposed_and_is_set_when_they_agree_in_a_later_turn(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            deposits_db = PoolDatabase(db_url, connect_timeout_s=5.0)
            await deposits_db.open()
            services.register(Deposits, PostgresDeposits(deposits_db))
            services.register(Proposals, PostgresProposals(deposits_db))
            try:
                args: dict[str, object] = {"for": "Alana", "at": tomorrow_at(18), "what": "turn the porch light off",
                                           "tools": ["switch"], "delivery": "quiet"}
                made = body(await call(tools_for(w, turn=5), "remind", args))
                assert made["armed"] is False and w.waiting() == []
                same = await call(tools_for(w, turn=5), "arm_reminder", {})
                assert same.is_error and same.content.startswith("same_turn") and w.waiting() == []
                armed = body(await call(tools_for(w, turn=6), "arm_reminder", {}))
                [(wake_id, due)] = w.waiting()
                assert armed["id"] == wake_id and due.astimezone(DENVER).hour == 18
                assert scalar(db_url, "SELECT json_build_array(route, tools, made_by = person_id) FROM wakes "
                                      "WHERE id = %s", (wake_id,)) == ["quiet", ["switch"], True]
                again = await call(tools_for(w, turn=7), "arm_reminder", {})
                assert again.is_error and again.content.startswith("none")
            finally:
                services.unregister(Deposits)
                services.unregister(Proposals)
                await deposits_db.close()
    run(go())


def test_a_reminder_that_only_looks_is_set_at_once_and_one_naming_a_tool_she_lacks_is_refused(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            args: dict[str, object] = {"for": "Alana", "at": tomorrow_at(18), "what": "check", "tools": ["look"]}
            body(await call(tools_for(w), "remind", args))
            assert len(w.waiting()) == 1
            refused = await call(tools_for(w), "remind", {**args, "tools": ["delete_everything"]})
            assert refused.is_error and refused.content.startswith("bad_arguments") and len(w.waiting()) == 1
            elsewhere = await call(tools_for(w), "remind", {**args, "for": "Sam", "tools": ["switch"]})
            assert elsewhere.is_error and elsewhere.content.startswith("bad_arguments") and len(w.waiting()) == 1
    run(go())


def test_tools_are_offered_to_a_reminder_only_in_a_private_turn_that_can_propose(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            async def offered(tools: ReminderTools) -> bool:
                (remind, *_) = (await tools.catalogue()).specs
                return "tools" in json.dumps(remind.parameters)
            kept = Switchboard()
            assert await offered(tools_for(w))
            assert not await offered(ReminderTools(w.home, w.alana, private=True, turn=(1, 5)))
            assert not await offered(ReminderTools(w.home, w.alana, private=True, usable=lambda: kept))
            assert not await offered(ReminderTools(w.home, w.alana, private=False, turn=(1, 5), usable=lambda: kept))
    run(go())


def test_change_reminder_moves_the_time_keeping_its_id_and_a_repeat_keeps_its_weekdays(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            made = body(await call(tools_for(w), "remind", {
                "for": "Alana", "at": tomorrow_at(8), "what": "take my meds", "repeat": "weekly",
                "weekdays": ["mon", "tue", "wed", "thu", "fri"]}))["id"]
            moved = body(await call(tools_for(w), "change_reminder", {"id": made, "at": tomorrow_at(9)}))
            [(wake_id, due)] = w.waiting()
            assert moved["changed"] == made == wake_id and due.astimezone(DENVER).hour == 9
            assert due.astimezone(DENVER).weekday() < 5
            stopped = body(await call(tools_for(w), "change_reminder", {"id": made, "count": 3}))
            assert stopped["changed"] == made
            (listed,) = (await w.wakes.reminders(w.home, w.alana))
            assert listed.reminder.repeat is not None and listed.reminder.repeat.until is not None
            assert listed.reminder.repeat.weekdays == (0, 1, 2, 3, 4)
            once = body(await call(tools_for(w), "change_reminder", {"id": made, "repeat": "none", "what": "meds"}))
            (listed,) = (await w.wakes.reminders(w.home, w.alana))
            assert once["changed"] == made and listed.reminder.repeat is None and listed.reminder.brief == "meds"
            assert isinstance(made, int)
            gone = await call(tools_for(w), "change_reminder", {"id": made + 50, "what": "x"})
            assert gone.is_error and gone.content.startswith("not_found")
    run(go())


def test_giving_a_reminder_tools_that_act_is_a_proposal_changing_nothing_until_agreed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            db = PoolDatabase(db_url, connect_timeout_s=5.0)
            await db.open()
            services.register(Deposits, PostgresDeposits(db))
            services.register(Proposals, PostgresProposals(db))
            try:
                made = body(await call(tools_for(w), "remind", {"for": "Alana", "at": tomorrow_at(18), "what": "x"}))["id"]
                proposed = body(await call(tools_for(w, turn=5), "change_reminder", {"id": made, "tools": ["switch"]}))
                assert proposed["armed"] is False
                (before,) = await w.wakes.reminders(w.home, w.alana)
                assert before.reminder.tools is None
                done = body(await call(tools_for(w, turn=6), "arm_reminder", {}))
                (after,) = await w.wakes.reminders(w.home, w.alana)
                assert done["changed"] == made and after.id == made and after.reminder.tools == ("switch",)
                trimmed = body(await call(tools_for(w, turn=8), "change_reminder", {"id": made, "tools": ["look"]}))
                assert trimmed["changed"] == made
                (last,) = await w.wakes.reminders(w.home, w.alana)
                assert last.reminder.tools == ("look",)
            finally:
                services.unregister(Deposits)
                await db.close()
    run(go())


def test_a_reminder_that_waits_on_money_has_no_time_to_change(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            db = PoolDatabase(db_url, connect_timeout_s=5.0)
            await db.open()
            deposits = PostgresDeposits(db)
            services.register(Deposits, deposits)
            try:
                armed = await deposits.arm(Reminder(w.home, w.alana, w.alana, "move it", datetime.now(UTC), None),
                                           DepositRule("a", "A", 1))
                refused = await call(tools_for(w), "change_reminder", {"id": armed, "at": tomorrow_at(9)})
                assert refused.is_error and refused.content.startswith("bad_arguments")
                said = body(await call(tools_for(w), "change_reminder", {"id": armed, "what": "move all of it"}))
                assert said["changed"] == armed
            finally:
                services.unregister(Deposits)
                await db.close()
    run(go())


def test_remind_with_weekdays_starts_on_the_first_such_day_and_a_count_ends_the_series(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            start = (datetime.now(DENVER) + timedelta(days=1)).strftime("%Y-%m-%d")
            made = body(await call(tools_for(w), "remind", {
                "for": "Alana", "at": f"{start}T08:00", "what": "water the plants", "repeat": "weekly",
                "weekdays": ["sun"], "count": 6}))
            [(_, due)] = w.waiting()
            assert due.astimezone(DENVER).weekday() == 6 and str(made["at"]).endswith("T08:00")
            (listed,) = await w.wakes.reminders(w.home, w.alana)
            repeat = listed.reminder.repeat
            assert repeat is not None and repeat.until == (due.astimezone(DENVER) + timedelta(weeks=5)).date()
            both = await call(tools_for(w), "remind", {"for": "Alana", "at": f"{start}T08:00", "what": "x",
                                                       "repeat": "weekly", "until": "2099-01-01", "count": 2})
            assert both.is_error and len(w.waiting()) == 1
    run(go())


def test_a_proposed_reminder_is_refused_once_its_time_has_passed_but_a_change_or_a_rule_is_not() -> None:
    now = datetime.now(UTC)
    gone = Reminder(1, 2, 2, "x", now - timedelta(minutes=1), None, None, "phone", ("switch",))
    at = now - timedelta(hours=1)
    assert refusal(Proposal(1, 2, 1, 5, at, ReminderSchedule(gone)), 6, now, 7200) == "expired"
    assert refusal(Proposal(1, 2, 1, 5, at, ReminderChange(gone, 9)), 6, now, 7200) is None
    assert refusal(Proposal(1, 2, 1, 5, at, MoneyRule(gone, DepositRule("a", "A", 1))), 6, now, 7200) is None
    ahead = Reminder(1, 2, 2, "x", now + timedelta(hours=1), None, None, "phone", ("switch",))
    assert refusal(Proposal(1, 2, 1, 5, at, ReminderSchedule(ahead)), 6, now, 7200) is None


def test_a_repeat_whose_first_time_has_passed_starts_at_its_next_one_after_now(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            day = datetime.now(DENVER) - timedelta(days=1)
            while day.weekday() >= 5:
                day -= timedelta(days=1)
            yesterday = day.strftime("%Y-%m-%dT08:00")
            body(await call(tools_for(w), "remind", {
                "for": "Alana", "at": yesterday, "what": "take my meds", "repeat": "weekly",
                "weekdays": ["mon", "tue", "wed", "thu", "fri"]}))
            [(_, due)] = w.waiting()
            local = due.astimezone(DENVER)
            assert due > datetime.now(UTC) and local.weekday() < 5 and (local.hour, local.minute) == (8, 0)
            passed = await call(tools_for(w), "remind", {"for": "Alana", "at": yesterday, "what": "once"})
            assert passed.is_error and passed.content.startswith("bad_arguments") and len(w.waiting()) == 1
    run(go())
