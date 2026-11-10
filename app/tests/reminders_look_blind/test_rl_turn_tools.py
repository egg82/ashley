"""What a reminder's turn offers (`reminder_turn.inbound` sets `reads_only`, `turn_tools.for_turn` narrows by it): only
tools whose spec says `reads`, and only where the reply reaches the person alone; none otherwise; a changing tool is
never offered or callable; without `reads_only` nothing changes."""

import asyncio
from dataclasses import replace

import pytest
from ashley import services
from ashley.channels.audience import owner_alone
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.inference.model import ToolCall
from ashley.tools.tools import Tools
from ashley.people.model import Person
from ashley.people.people import People
from reminders_look_blind_support import ALANA, Home, CHANGES, LANDED, READS, Listed, SAM, mixed, offered, reminder, spec, turn
from ashley.channels.wake.reminder_turn import inbound as reminder_inbound

WEB = Inbound(household_id=5, thread="person:11:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=11, shared=False, place=None, channel="web", later=True, later_by="turn")


def wired(source: Listed | None = None) -> Listed:
    source = source or mixed()
    services.register(Tools, source)
    services.register(People, Home())
    return source


def test_a_reminder_turn_asks_for_reads_only_and_still_goes_out() -> None:
    for landed in (None, LANDED):
        got = turn(landed)
        assert got.reads_only is True and got.promised is True and got.unprompted is True
        assert owner_alone(got)


def test_a_reminder_turn_offers_the_tools_that_read_and_none_that_change() -> None:
    wired()
    got = offered(for_turn(turn()))
    assert set(READS) <= set(got)
    assert not set(CHANGES) & set(got)


@pytest.mark.parametrize("who", [ALANA, SAM])
def test_every_tool_a_reminder_turn_offers_reads(who: Person) -> None:
    wired()
    catalogue = asyncio.run(for_turn(turn(who=who)).catalogue())
    assert catalogue.specs and all(s.reads for s in catalogue.specs)


@pytest.mark.parametrize("name", ["remind", "remind_on_money", "cancel_reminder"])
def test_the_reminder_tools_that_set_or_cancel_are_not_offered_to_a_reminder_turn(name: str) -> None:
    wired()
    assert name not in offered(for_turn(turn()))


@pytest.mark.parametrize("name", CHANGES)
def test_a_changing_tool_named_in_the_catalogue_is_refused_on_a_reminder_turn_and_never_runs(name: str) -> None:
    source = wired()
    tools = for_turn(turn())
    asyncio.run(tools.catalogue())
    got = asyncio.run(tools.call(ToolCall("c", name, {})))
    assert got.is_error and source.called == []


def test_a_changing_tool_is_refused_even_if_called_before_the_catalogue_was_asked() -> None:
    source = wired()
    assert asyncio.run(for_turn(turn()).call(ToolCall("c", "lamp_on", {}))).is_error and source.called == []


def test_a_tool_that_reads_still_runs_on_a_reminder_turn() -> None:
    source = wired()
    got = asyncio.run(for_turn(turn()).call(ToolCall("c", "balance", {})))
    assert not got.is_error and source.called == ["balance"]


def test_a_catalogue_of_only_changing_tools_leaves_a_reminder_turn_none_of_them() -> None:
    wired(Listed(tuple(spec(n, False) for n in CHANGES)))
    got = offered(for_turn(turn()))
    assert not set(CHANGES) & set(got)


@pytest.mark.parametrize("changes", [
    {"audience": "present"}, {"audience": "household"}, {"shared": True}, {"device_id": 7}, {"speaker_id": None},
    {"audience": "present", "shared": True, "device_id": 7, "place": "kitchen"}])
def test_where_the_reply_does_not_reach_the_speaker_alone_it_offers_no_tool_at_all(changes: dict[str, object]) -> None:
    source = wired()
    got = replace(turn(), **changes)
    assert not owner_alone(got)
    tools = for_turn(got)
    assert offered(tools) == []
    for name in (*READS, *CHANGES):
        assert asyncio.run(tools.call(ToolCall("c", name, {}))).is_error
    assert source.called == []


def test_reads_only_on_a_shared_voice_turn_offers_none_where_without_it_the_house_tools_stay() -> None:
    wired()
    voice = Inbound(household_id=5, thread="device:7", text="hi", kind="command", medium="spoken", audience="present",
                    speaker_id=None, shared=True, place="kitchen", channel="voice")
    assert set(offered(for_turn(voice))) == {*READS, *CHANGES}
    assert offered(for_turn(replace(voice, reads_only=True))) == []


def test_without_reads_only_a_turn_keeps_every_tool_it_always_offered() -> None:
    wired()
    got = offered(for_turn(WEB))
    assert set(got) >= {*READS, *CHANGES, "remind"}
    assert set(CHANGES) <= set(offered(for_turn(replace(turn(), reads_only=False))))


def test_reads_only_removes_from_the_same_turn_exactly_what_changes() -> None:
    wired()
    free = replace(turn(), reads_only=False)
    full, narrowed = offered(for_turn(free)), offered(for_turn(turn()))
    assert set(narrowed) < set(full) and set(CHANGES) <= set(full) - set(narrowed)
    assert [n for n in full if n in narrowed] == narrowed


def test_reads_only_on_a_persons_own_web_chat_drops_opening_a_bench_and_every_change() -> None:
    wired()
    got = offered(for_turn(replace(WEB, reads_only=True, opens_benches=True)))
    assert set(READS) <= set(got)
    assert not {"open_bench", "remind", "cancel_reminder", *CHANGES} & set(got)


def test_named_tools_and_reads_only_together_offer_only_the_named_that_read() -> None:
    wired()
    got = offered(for_turn(turn(tools_only=("lamp_on", "look_up"))))
    assert got == ["look_up"]


def test_a_repeating_reminder_turn_is_the_same() -> None:
    from ashley.senses.repeat import Repeat
    from datetime import datetime
    rep = replace(reminder(), repeat=Repeat("daily", 1, datetime(2026, 11, 3, 9, 0)))
    got = reminder_inbound(31, rep, ALANA, ALANA)
    assert got.reads_only is True and got.promised is True
