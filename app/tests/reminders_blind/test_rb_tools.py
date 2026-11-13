"""`ReminderTools`: remind, reminders and cancel_reminder by structured fields; a person outside the household is refused;
a reminder is listed and cancelled only where the reply reaches the speaker alone; nothing a reminder says is logged."""

import json
from collections.abc import Generator, Mapping
from typing import Any
from datetime import timedelta

import pytest
from ashley import logs, services
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.people.model import Household, Person
from ashley.people.people import People
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Delivery, Due, Outcome, State, Received, Reminder, Route, SaidBefore, Scheduled, Wake, Wakes, WakesUnavailable
from ashley.tools.reminders import ReminderTools
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from datetime import datetime
from rb_support import PLANTED, ZONE, Folk, now

HOUSE = 7
ALANA, SAM, KIM = Person(1, HOUSE, "Alana"), Person(2, HOUSE, "Sam"), Person(3, HOUSE, "Kim")


class Memory(Wakes):
    """The documented behaviour of the reminder half of Wakes, in memory."""

    def __init__(self) -> None:
        self.items: dict[int, Reminder] = {}
        self.cancelled: list[int] = []
        self.states: dict[int, State] = {}
        self.down = False

    async def receive(self, device_id: int, wake: Wake) -> Received:
        raise AssertionError("a tool never receives a house wake")

    async def schedule(self, reminder: Reminder) -> int:
        if self.down:
            raise WakesUnavailable("down")
        if not 1 <= len(reminder.brief) <= 500 or "\x00" in reminder.brief:
            raise ValueError("brief")
        self.items[len(self.items) + 1] = reminder
        return len(self.items)

    async def due(self, limit: int) -> tuple[Due, ...]:
        return ()

    async def settle(self, wake_id: int, outcome: Outcome, next_due: datetime | None = None) -> bool:
        return False

    async def reminders(self, household_id: int, person_id: int) -> tuple[Scheduled, ...]:
        return tuple(Scheduled(i, r, self.states.get(i, "scheduled")) for i, r in self.items.items()
                     if i not in self.cancelled and r.household_id == household_id and person_id in (r.person_id, r.made_by))

    async def cancel(self, household_id: int, person_id: int, wake_id: int) -> bool:
        found = [s.id for s in await self.reminders(household_id, person_id)]
        if wake_id not in found:
            return False
        self.cancelled.append(wake_id)
        return True

    async def edit(self, household_id: int, person_id: int, wake_id: int, changed: Reminder) -> bool:
        found = [s.id for s in await self.reminders(household_id, person_id)]
        if wake_id not in found:
            return False
        self.items[wake_id] = changed
        return True

    async def routed(self, wake_id: int, person_id: int, route: Route, device_id: int) -> None:
        return None

    async def prune(self, older_than_s: float) -> int:
        return 0

    async def refire(self, wake_id: int, after_s: float) -> int:
        return 0

    async def undelivered(self, limit: int, retry_s: float, within_s: float, *, at: Route = "phone", device_tries: int = 0,
                          device_retry_s: float = 0.0) -> tuple[Delivery, ...]:
        return ()

    async def claim(self, wake_id: int, retry_s: float, *, at: Route = "phone", device_tries: int = 0,
                    device_retry_s: float = 0.0) -> bool:
        return False

    async def delivered(self, wake_id: int, reached: bool) -> None:
        return None

    async def dismiss(self, household_id: int, person_id: int, wake_id: int) -> bool:
        return False

    async def said_before(self, wake_id: int, person_id: int) -> SaidBefore:
        raise AssertionError("a tool never reads a house wake's history")


@pytest.fixture
def memory() -> Generator[Memory]:
    m = Memory()
    services.register(Wakes, m)
    services.register(People, Folk(Household(HOUSE, "home", "America/Denver", "", (ALANA, SAM, KIM))))
    yield m
    services.unregister(Wakes)
    services.unregister(People)


def tools(speaker: Person = ALANA, private: bool = True) -> ReminderTools:
    return ReminderTools(HOUSE, speaker.id, private=private)


def use(t: ReminderTools, name: str, args: dict[str, object]) -> ToolResult:
    out: list[ToolResult] = []

    async def go() -> None:
        out.append(await t.call(ToolCall("c1", name, args)))

    run(go())
    return out[0]


def names(t: ReminderTools) -> list[str]:
    box: list[list[str]] = []

    async def go() -> None:
        box.append([s.name for s in (await t.catalogue()).specs])

    run(go())
    return box[0]


def in_days(n: int) -> str:
    return (now().astimezone(ZONE) + timedelta(days=n)).strftime("%Y-%m-%dT%H:%M")


def test_remind_offers_for_as_the_households_names_and_structured_fields_only(memory: Memory) -> None:
    box: list[tuple[ToolSpec, ...]] = []

    async def go() -> None:
        box.append((await tools().catalogue()).specs)

    run(go())
    (spec,) = [x for x in box[0] if x.name == "remind"]
    params: Mapping[str, Any] = spec.parameters
    assert sorted(params["properties"]["for"]["enum"]) == ["Alana", "Kim", "Sam"]
    assert set(params["properties"]) >= {"for", "at", "what"}
    assert {"for", "at", "what"} <= set(params["required"])


def test_listing_and_cancelling_are_offered_only_where_the_reply_reaches_the_speaker_alone(memory: Memory) -> None:
    assert names(tools(private=True)) == ["remind", "reminders", "cancel_reminder", "change_reminder"]
    assert names(tools(private=False)) == ["remind"]


def test_remind_schedules_a_reminder_for_the_speaker_in_the_households_wall_clock(memory: Memory) -> None:
    when = in_days(3)
    got = use(tools(), "remind", {"for": "Alana", "at": when, "what": PLANTED})
    assert not got.is_error
    ((id_, r),) = memory.items.items()
    assert str(id_) in got.content
    assert (r.household_id, r.person_id, r.made_by, r.brief, r.repeat) == (HOUSE, ALANA.id, ALANA.id, PLANTED, None)
    assert r.due_at.astimezone(ZONE).strftime("%Y-%m-%dT%H:%M") == when


def test_remind_for_another_person_of_the_household_is_made_by_the_speaker(memory: Memory) -> None:
    got = use(tools(ALANA), "remind", {"for": "Sam", "at": in_days(2), "what": "bring the bins in"})
    assert not got.is_error
    (r,) = memory.items.values()
    assert (r.person_id, r.made_by) == (SAM.id, ALANA.id)


@pytest.mark.parametrize("name", ["Zed", "", "alana ", "Alana; DROP", "someone from another household"])
def test_a_person_outside_the_household_is_refused_and_nothing_is_scheduled(memory: Memory, name: str) -> None:
    got = use(tools(), "remind", {"for": name, "at": in_days(2), "what": "x"})
    assert got.is_error and memory.items == {}


def test_a_repeating_reminder_carries_its_rule_anchored_at_the_first_time(memory: Memory) -> None:
    when = in_days(5)
    got = use(tools(), "remind", {"for": "Alana", "at": when, "repeat": "monthly", "every": 2, "what": "rent"})
    assert not got.is_error
    (r,) = memory.items.values()
    assert r.repeat == Repeat("monthly", 2, datetime.fromisoformat(when))


def test_repeat_without_every_is_every_one_and_none_is_once(memory: Memory) -> None:
    when = in_days(5)
    use(tools(), "remind", {"for": "Alana", "at": when, "repeat": "weekly", "what": "a"})
    use(tools(), "remind", {"for": "Alana", "at": when, "repeat": "none", "what": "b"})
    a, b = memory.items.values()
    assert a.repeat == Repeat("weekly", 1, datetime.fromisoformat(when)) and b.repeat is None


BAD: list[dict[str, object]] = [
    {"for": "Alana", "at": "tomorrow at nine", "what": "x"}, {"for": "Alana", "at": "2026-13-45T99:99", "what": "x"},
    {"for": "Alana", "at": "2020-01-01T09:00", "what": "x"}, {"for": "Alana", "at": in_days(2), "what": ""},
    {"for": "Alana", "at": in_days(2), "what": "x" * 501}, {"for": "Alana", "at": in_days(2), "what": "x", "repeat": "hourly"},
    {"for": "Alana", "at": in_days(2), "what": "x", "repeat": "daily", "every": 0},
    {"for": "Alana", "at": in_days(2), "what": "x", "repeat": "daily", "every": -2},
    {"for": "Alana", "at": in_days(2), "what": "x", "repeat": "daily", "every": 1001},
    {"for": "Alana", "at": in_days(2)}, {"at": in_days(2), "what": "x"}, {"for": "Alana", "what": "x"}, {},
    {"for": "Alana", "at": in_days(2), "what": "x", "when": "tomorrow"}, {"for": "Alana", "at": in_days(2), "what": "x", "recur": "daily"},
    {"for": 5, "at": in_days(2), "what": "x"}, {"for": "Alana", "at": 5, "what": "x"}]


@pytest.mark.parametrize("args", BAD)
def test_a_bad_argument_or_a_time_already_passed_is_an_error_result_and_schedules_nothing(
        memory: Memory, args: dict[str, object]) -> None:
    got = use(tools(), "remind", args)
    assert got.is_error and memory.items == {}


def test_an_unknown_tool_is_an_error_result(memory: Memory) -> None:
    assert use(tools(), "set_alarm", {}).is_error


def test_the_store_being_down_is_an_error_result_not_a_raise(memory: Memory) -> None:
    memory.down = True
    assert use(tools(), "remind", {"for": "Alana", "at": in_days(2), "what": "x"}).is_error


def test_reminders_lists_the_speakers_own_and_nobody_elses(memory: Memory) -> None:
    use(tools(ALANA), "remind", {"for": "Alana", "at": in_days(2), "what": "ALANAS-ONE-zq"})
    use(tools(ALANA), "remind", {"for": "Sam", "at": in_days(3), "what": "FOR-SAM-zq"})
    use(tools(KIM), "remind", {"for": "Kim", "at": in_days(4), "what": "KIMS-OWN-zq"})
    mine = use(tools(ALANA), "reminders", {})
    assert not mine.is_error and "ALANAS-ONE-zq" in mine.content and "FOR-SAM-zq" in mine.content
    assert "KIMS-OWN-zq" not in mine.content
    assert "ALANAS-ONE-zq" not in use(tools(KIM), "reminders", {}).content


def test_listing_where_the_reply_is_not_private_is_refused_and_says_nothing(memory: Memory) -> None:
    use(tools(ALANA), "remind", {"for": "Alana", "at": in_days(2), "what": "SECRET-zq"})
    got = use(tools(ALANA, private=False), "reminders", {})
    assert got.is_error and "SECRET-zq" not in got.content
    still = use(tools(ALANA, private=False), "cancel_reminder", {"id": 1})
    assert still.is_error and memory.cancelled == []


def test_cancel_reminder_cancels_the_speakers_own_by_id(memory: Memory) -> None:
    use(tools(ALANA), "remind", {"for": "Alana", "at": in_days(2), "what": "x"})
    got = use(tools(ALANA), "cancel_reminder", {"id": 1})
    assert not got.is_error and memory.cancelled == [1]


def test_either_side_of_a_reminder_set_for_another_may_cancel_it(memory: Memory) -> None:
    use(tools(ALANA), "remind", {"for": "Sam", "at": in_days(2), "what": "x"})
    assert not use(tools(SAM), "cancel_reminder", {"id": 1}).is_error and memory.cancelled == [1]


def test_cancelling_another_persons_or_a_missing_reminder_is_an_error_and_cancels_nothing(memory: Memory) -> None:
    use(tools(ALANA), "remind", {"for": "Alana", "at": in_days(2), "what": "x"})
    assert use(tools(KIM), "cancel_reminder", {"id": 1}).is_error
    assert use(tools(ALANA), "cancel_reminder", {"id": 99}).is_error
    assert use(tools(ALANA), "cancel_reminder", {"id": "one"}).is_error
    assert use(tools(ALANA), "cancel_reminder", {}).is_error
    assert memory.cancelled == []


def test_nothing_a_reminder_says_or_is_for_reaches_a_log(memory: Memory, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    use(tools(), "remind", {"for": "Sam", "at": in_days(2), "what": PLANTED})
    use(tools(), "reminders", {})
    use(tools(), "cancel_reminder", {"id": 1})
    use(tools(), "remind", {"for": "Alana", "at": "PLANTED-BAD-TIME", "what": PLANTED})
    out = capsys.readouterr()
    text = out.out + out.err
    assert "tools.call" in text
    assert "PLANTED" not in text and "500 dollars" not in text and "Sam" not in text


def test_the_tools_work_against_the_real_wakes_on_a_database(db_url: str) -> None:
    from ashley.db.pool import PoolDatabase
    from ashley.senses.postgres_wakes import PostgresWakes
    from contract.conversations_support import household, person

    house = household(db_url)
    alana, sam = person(db_url, house, "Alana"), person(db_url, house, "Sam")

    async def go() -> None:
        db = PoolDatabase(db_url, connect_timeout_s=5.0)
        await db.open()
        try:
            real = PostgresWakes(db)
            services.register(Wakes, real)
            services.register(People, Folk(Household(house, "home", "America/Denver", "", (Person(alana, house, "Alana"), Person(sam, house, "Sam")))))
            t = ReminderTools(house, alana, private=True)
            when = in_days(4)
            made = await t.call(ToolCall("c", "remind", {"for": "Sam", "at": when, "repeat": "monthly", "what": PLANTED}))
            assert not made.is_error
            (listed,) = await real.reminders(house, sam)
            assert (listed.reminder.person_id, listed.reminder.made_by) == (sam, alana)
            assert listed.reminder.due_at.astimezone(ZONE).strftime("%Y-%m-%dT%H:%M") == when
            cancelled = await ReminderTools(house, sam, private=True).call(ToolCall("c", "cancel_reminder", {"id": listed.id}))
            assert not cancelled.is_error and await real.reminders(house, sam) == ()
        finally:
            services.unregister(Wakes)
            services.unregister(People)
            await db.close()

    run(go())


def on_day(n: int) -> str:
    return (now().astimezone(ZONE) + timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.mark.parametrize("days", [1, 2, 9, 40, 140, 200])
def test_a_date_alone_is_nine_in_the_morning_that_day_in_the_households_zone(memory: Memory, days: int) -> None:
    day = on_day(days)
    got = use(tools(), "remind", {"for": "Alana", "at": day, "what": "the bins"})
    assert not got.is_error
    (r,) = memory.items.values()
    assert r.due_at.astimezone(ZONE).strftime("%Y-%m-%dT%H:%M") == f"{day}T09:00"
    assert r.due_at.utcoffset() is not None and r.repeat is None


def test_a_date_alone_is_the_same_instant_as_nine_spelled_out(memory: Memory) -> None:
    day = on_day(3)
    use(tools(), "remind", {"for": "Alana", "at": day, "what": "a"})
    use(tools(), "remind", {"for": "Alana", "at": f"{day}T09:00", "what": "b"})
    a, b = memory.items.values()
    assert a.due_at == b.due_at


def test_a_repeating_reminder_set_by_date_alone_is_anchored_at_nine(memory: Memory) -> None:
    day = on_day(5)
    got = use(tools(), "remind", {"for": "Alana", "at": day, "repeat": "monthly", "what": "rent"})
    assert not got.is_error
    (r,) = memory.items.values()
    assert r.repeat == Repeat("monthly", 1, datetime.fromisoformat(f"{day}T09:00"))


def test_a_date_alone_today_is_nine_today_or_refused_once_nine_has_passed(memory: Memory) -> None:
    local = now().astimezone(ZONE)
    got = use(tools(), "remind", {"for": "Alana", "at": on_day(0), "what": "x"})
    if (local.hour, local.minute) >= (9, 0):
        assert got.is_error and memory.items == {}
    else:
        assert not got.is_error and len(memory.items) == 1


@pytest.mark.parametrize("at", ["2030-1-5", "2030-01-05T", "2030-02-30", "05-01-2030", "2030-01-05 09:00", "20300105",
                                "2030-W01-1", "2030-01-05T0900", "2030-01-05T09", "2030-01-05T09:00:30", "2030-01-05T09:00Z",
                                "2030-01-05T25:00", " 2030-01-05", "2030-01-05\n"])
def test_a_malformed_date_is_an_error_result_and_schedules_nothing(memory: Memory, at: str) -> None:
    got = use(tools(), "remind", {"for": "Alana", "at": at, "what": "x"})
    assert got.is_error and memory.items == {}


def test_a_one_digit_hour_is_refused_as_the_schema_says(memory: Memory) -> None:
    got = use(tools(), "remind", {"for": "Alana", "at": f"{on_day(3)}T9:00", "what": "x"})
    assert got.is_error and memory.items == {}


def test_the_reminders_tool_says_where_each_one_stands(memory: Memory) -> None:
    for what in ("a", "b", "c"):
        use(tools(), "remind", {"for": "Alana", "at": in_days(2), "what": what})
    memory.states.update({2: "undelivered", 3: "failed"})
    got = use(tools(), "reminders", {})
    assert not got.is_error
    shown = {r["what"]: r["state"] for r in json.loads(got.content)["reminders"]}
    assert shown == {"a": "scheduled", "b": "undelivered", "c": "failed"}
