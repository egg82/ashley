"""A person's own quiet hours (`ashley.people.quiet`, `Initiative`): the window in its own zone, across midnight, at its
edges and across a daylight-saving change; and that nothing she does unprompted reaches the person inside it (a
remark, a greeting, a house notice) while a reply to them, and a reminder they asked for, still do."""

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from ashley import services
from ashley.channels import unprompted
from ashley.channels.model import Inbound
from ashley.channels.wake import wake_turn, watch_turn
from ashley.channels.checkpoint import dumps, loads
from ashley.inference.reply import Reply
from ashley.initiative.initiative import Initiative, NullInitiative, Scored
from ashley.initiative.moment import Moment
from ashley.initiative.remark import Chance, Rates, verdict
from ashley.initiative.weights import parse
from ashley.people.model import Person, QuietHours
from ashley.people.quiet import held, holds
from ashley.senses.wakes import Wake, WatchWake
from ashley.workshop.wake_rule import WakeRule
from inflight_blind.ifb_checkpoint_support import checkpoint
from household_routes_support import events
from initiative_support import weights
from watch_job_support import watch as a_watch

NIGHT = QuietHours(22, 7, "UTC")
DAY = QuietHours(9, 17, "UTC")
ALWAYS = Rates(chance=1.0, per_day=2, typing_within_s=900.0, repeat_within_days=30)
HOUSE_NIGHT = parse(weights(night={"weight": 0.0, "from_hour": 1, "to_hour": 2}))
SAYS = Reply(spoken="hi", text="hi", says="reply")


def at(hour: int, minute: int = 0, zone: timezone = UTC) -> datetime:
    return datetime(2026, 1, 15, hour, minute, tzinfo=zone)


def test_a_window_inside_one_day_holds_from_its_start_up_to_but_not_its_end() -> None:
    got = {h: holds(DAY, at(h)) for h in (8, 9, 16, 17)}
    assert got == {8: False, 9: True, 16: True, 17: False}
    assert holds(DAY, at(16, 59)) is True and holds(DAY, at(8, 59)) is False


def test_a_window_across_midnight_holds_on_both_sides_of_it() -> None:
    got = {h: holds(NIGHT, at(h)) for h in (21, 22, 23, 0, 6, 7, 12)}
    assert got == {21: False, 22: True, 23: True, 0: True, 6: True, 7: False, 12: False}


def test_the_window_is_read_in_the_zone_it_names_not_the_instants() -> None:
    nine_pm_utc = at(21)
    denver = replace(NIGHT, timezone="America/Denver")
    tokyo = replace(NIGHT, timezone="Asia/Tokyo")
    assert holds(NIGHT, nine_pm_utc) is False
    assert holds(denver, nine_pm_utc) is False, "2 pm there"
    assert holds(tokyo, nine_pm_utc) is True, "6 am there, still inside"
    assert holds(denver, at(5)) is True, "10 pm the evening before there"
    assert holds(denver, at(13, 59)) is True and holds(denver, at(14)) is False, "6:59 am there is in, 7 am is out"


def test_the_same_instant_is_asked_in_another_zone_and_an_aware_instant_in_any_offset_agrees() -> None:
    plus_two = timezone(timedelta(hours=2))
    assert holds(NIGHT, at(0, 30, plus_two)) is holds(NIGHT, at(22, 30, UTC)) is True
    assert holds(NIGHT, at(10, 0, plus_two)) is holds(NIGHT, at(8, 0, UTC)) is False


def test_daylight_saving_moves_the_window_with_the_zone() -> None:
    london = QuietHours(1, 5, "Europe/London")
    summer, winter = datetime(2026, 7, 1, 0, 30, tzinfo=UTC), datetime(2026, 1, 1, 0, 30, tzinfo=UTC)
    assert holds(london, summer) is True, "01:30 in London in July"
    assert holds(london, winter) is False, "00:30 in London in January"


def test_none_set_is_no_hold_and_an_unreadable_zone_is_unknown_never_a_value() -> None:
    assert holds(None, at(23)) is False
    assert holds(QuietHours(22, 7, "Mars/Olympus"), at(23)) is None
    assert held(Person(1, 1, "A"), at(23)) is False
    assert held(Person(1, 1, "A", quiet=QuietHours(22, 7, "Mars/Olympus")), at(12)) is True
    assert held(Person(1, 1, "A", quiet=NIGHT), at(12)) is False and held(Person(1, 1, "A", quiet=NIGHT), at(23)) is True


def chance(**changes: object) -> Chance:
    return replace(Chance("discord:1", hour=12, sent=0, since_typed_s=None, typing_known=True, quiet=False), **changes)


def test_a_remark_is_refused_inside_the_persons_quiet_hours_and_unknown_hours_keep_her_out() -> None:
    assert verdict(chance(), ALWAYS, HOUSE_NIGHT) == "allowed"
    assert verdict(chance(quiet=True), ALWAYS, HOUSE_NIGHT) == "quiet"
    assert verdict(chance(quiet=None), ALWAYS, HOUSE_NIGHT) == "unknown"


def test_the_households_night_is_still_named_first_and_quiet_before_typing_and_the_cap() -> None:
    assert verdict(chance(hour=1, quiet=True), ALWAYS, HOUSE_NIGHT) == "night"
    assert verdict(chance(quiet=True, since_typed_s=1.0, sent=9), ALWAYS, HOUSE_NIGHT) == "quiet"


def turn(quiet: bool = False, promised: bool = False) -> Inbound:
    return Inbound(household_id=1, thread="push:5", text="the washer finished", kind="chat", medium="text",
                   audience="owner", speaker_id=5, shared=False, place=None, channel="device", later=True,
                   source="wake:1", unprompted=True, author="household", taint=None, quiet=quiet, promised=promised)


@pytest.fixture
def scored() -> Scored:
    return Scored(HOUSE_NIGHT, ALWAYS)


def test_an_unprompted_turn_for_a_person_in_quiet_hours_goes_nowhere_and_one_outside_them_goes_out(scored: Scored) -> None:
    assert scored.speaks(SAYS, None, False) is True
    assert scored.speaks(SAYS, None, True) is False
    assert scored.speaks(SAYS, Moment("wake:1"), True) is False, "a greeting too, whatever its plan"
    assert NullInitiative().speaks(SAYS, None, False) is False


def test_the_turn_loop_keeps_a_quiet_turns_reply_out_and_records_her_staying_quiet(scored: Scored) -> None:
    services.register(Initiative, scored)
    try:
        assert unprompted.speaks(SAYS, turn(quiet=False)) and unprompted.says(SAYS, turn()) == "reply"
        held_back = turn(quiet=True)
        assert not unprompted.speaks(SAYS, held_back) and unprompted.says(SAYS, held_back) == "none"
        assert unprompted.as_said(SAYS, held_back).text != "hi" and not unprompted.as_said(SAYS, held_back).to_phone
    finally:
        services.unregister(Initiative)


def test_a_reply_to_the_person_and_a_reminder_they_asked_for_are_never_held(scored: Scored) -> None:
    services.register(Initiative, scored)
    try:
        assert unprompted.speaks(SAYS, replace(turn(quiet=True), unprompted=False))
        assert unprompted.speaks(SAYS, turn(quiet=True, promised=True))
    finally:
        services.unregister(Initiative)


def test_the_decision_logs_the_reason_for_a_quiet_turn(scored: Scored, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.channels")
    services.register(Initiative, scored)
    try:
        assert unprompted.decided(SAYS, turn(quiet=True), 9) is False
        assert unprompted.decided(SAYS, turn(quiet=False), 9) is True
    finally:
        services.unregister(Initiative)
    quiet, loud = events(caplog, "initiative.decided")
    assert quiet == {"conversation": 9, "speaks": False, "outcome": "quiet"}
    assert loud["outcome"] == "not_greeting" and loud["speaks"] is True


def test_a_house_wakes_turn_carries_whether_the_person_was_in_quiet_hours_at_the_event() -> None:
    rule = WakeRule("washer_done", "Tell them.", ())
    for hour, quiet in ((23, True), (12, False)):
        wake = Wake(1, "e1", "washer_done", "person.alana", None, at(hour))
        sleeping = Person(5, 1, "Alana", quiet=NIGHT)
        assert wake_turn.inbound(1, wake, rule, sleeping).quiet is quiet
        assert wake_turn.inbound(1, wake, rule, Person(5, 1, "Alana")).quiet is False, "none set"


def test_the_quiet_fact_survives_the_checkpoint_so_a_resumer_decides_the_same() -> None:
    base = checkpoint()
    got = loads(dumps(replace(base, inbound=replace(base.inbound, unprompted=True, quiet=True))))
    assert got.inbound.quiet is True and loads(dumps(base)).inbound.quiet is False
    remark = chance(quiet=True)
    assert loads(dumps(replace(base, inbound=replace(base.inbound, unprompted=True, remark=remark)))).inbound.remark == remark


def test_a_watchs_turn_is_held_on_the_phone_thread_but_never_on_a_bench_the_person_has_open() -> None:
    wake = WatchWake(1, 7, 1, "paused", {"what": "paused", "reason": "unreachable"})
    kept = a_watch()
    assert watch_turn.inbound(1, kept, wake, False, quiet=True).quiet is True
    assert watch_turn.inbound(1, kept, wake, False, quiet=False).quiet is False
    assert watch_turn.inbound(1, replace(kept, bench_id=3), wake, True, quiet=True).quiet is False
