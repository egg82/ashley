"""The payload kinds and their stored form: each kind belongs to one topic and is stored as a JSON object tagged by `kind`
that its topic decodes back whole; `check` and `lapsed` by the contract's sentences."""

import json
from datetime import timedelta

import pytest
from ashley.senses.proposal_payloads import HOUSE, MAX_BRIEF, MAX_TOOLS, REMINDERS, HouseChange, Payload, check, encode, lapsed
from ashley.home_assistant.change import Change
from ashley.senses.repeat import Repeat
from ashley.senses.wakes import Reminder
from ashley.senses.proposal_payloads import MoneyRule, ReminderChange, ReminderSchedule
from proposals_blind_support import NOW, clock, edit, house_change, money, reminder, schedule


def test_topics_are_named_as_stored() -> None:
    assert (REMINDERS.name, HOUSE.name) == ("reminder", "house")


@pytest.mark.parametrize("payload,topic", [(schedule(1, 1), "reminder"), (money(1, 1), "reminder"), (edit(1, 1), "reminder"),
                                           (house_change(), "house")])
def test_each_kind_is_stored_under_its_topic_as_a_json_object_with_a_kind(payload: Payload, topic: str) -> None:
    name, stored = encode(payload)
    assert name == topic
    assert isinstance(json.loads(json.dumps(stored)), dict)
    assert isinstance(stored["kind"], str) and stored["kind"]


def test_the_four_kinds_have_four_different_tags() -> None:
    tags = {encode(p)[1]["kind"] for p in (schedule(1, 1), money(1, 1), edit(1, 1), house_change())}
    assert len(tags) == 4


@pytest.mark.parametrize("payload", [schedule(1, 1), money(1, 1), edit(1, 2, 9), schedule(3, 4, "x" * MAX_BRIEF)])
def test_a_reminder_payload_decodes_whole_through_its_topic_after_a_json_round_trip(payload: Payload) -> None:
    _, stored = encode(payload)
    assert REMINDERS.decode(json.loads(json.dumps(stored))) == payload


@pytest.mark.parametrize("change", [Change("delete", "automation", "porch"),
                                    Change("perform", "action", "recorder.purge", {"keep_days": 1, "nested": {"a": [1, 2]}}),
                                    Change("perform", "action", "light.turn_off", {"transition": 3}, ("light.a", "light.b")),
                                    Change("write", "helper", None, {"name": "Guests"})])
def test_a_house_payload_decodes_whole_through_its_topic(change: Change) -> None:
    made = HouseChange(change, "a line for the person")
    assert HOUSE.decode(json.loads(json.dumps(encode(made)[1]))) == made


def test_a_reminder_with_a_repeat_and_tools_and_route_survives_the_stored_form() -> None:
    weekly = Repeat("weekly", 2, clock().replace(tzinfo=None, second=0, microsecond=0), (0, 2))
    r = Reminder(1, 2, 3, "brief", clock().replace(microsecond=0), weekly, route="quiet", tools=("a", "b"))
    made = ReminderSchedule(r)
    assert REMINDERS.decode(json.loads(json.dumps(encode(made)[1]))) == made


def test_only_a_reminder_to_schedule_lapses_with_its_time() -> None:
    soon = NOW + timedelta(hours=1)
    before, after = soon - timedelta(minutes=1), soon + timedelta(minutes=1)
    assert lapsed(schedule(1, 1, due_at=soon), before) is False
    assert lapsed(schedule(1, 1, due_at=soon), after) is True
    assert lapsed(schedule(1, 1, due_at=soon), soon) is True
    past = NOW - timedelta(days=9)
    assert lapsed(MoneyRule(reminder(1, 1, due_at=past), money(1, 1).rule), NOW) is False
    assert lapsed(ReminderChange(reminder(1, 1, due_at=past), 3), NOW) is False
    assert lapsed(house_change(), NOW) is False


def test_check_accepts_what_is_within_the_limits() -> None:
    check(schedule(1, 1, "x"))
    check(ReminderSchedule(reminder(1, 1, "x" * MAX_BRIEF, tools=tuple(f"t{i}" for i in range(MAX_TOOLS)))))
    check(money(1, 1))
    check(edit(1, 1))
    check(house_change())


@pytest.mark.parametrize("brief", ["", "x" * (MAX_BRIEF + 1), "a\x00b"])
def test_check_refuses_a_brief_outside_one_to_the_limit_or_with_a_nul(brief: str) -> None:
    r = reminder(1, 1, brief)
    for payload in (ReminderSchedule(r), ReminderChange(r, 3), MoneyRule(r, money(1, 1).rule)):
        with pytest.raises(ValueError):
            check(payload)


def test_check_refuses_more_tools_than_the_limit() -> None:
    with pytest.raises(ValueError):
        check(ReminderSchedule(reminder(1, 1, tools=tuple(f"t{i}" for i in range(MAX_TOOLS + 1)))))


def test_check_refuses_a_money_rule_that_repeats() -> None:
    weekly = Repeat("daily", 1, clock().replace(tzinfo=None))
    with pytest.raises(ValueError):
        check(MoneyRule(Reminder(1, 1, 1, "b", clock(), weekly), money(1, 1).rule))


def test_a_house_change_keeps_its_summary_and_change() -> None:
    made = HouseChange(house_change().change, "a line")
    assert made.summary == "a line" and made.change.op == "delete"


def test_check_accepts_a_repeating_reminder_that_is_not_a_money_rule() -> None:
    daily = Repeat("daily", 1, clock().replace(tzinfo=None))
    check(ReminderSchedule(Reminder(1, 1, 1, "b", clock(), daily)))
    check(ReminderChange(Reminder(1, 1, 1, "b", clock(), daily), 3))
