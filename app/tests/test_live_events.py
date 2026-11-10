"""Live's event model and its privacy rule: who an event may be shown to, its round trip between pods, and one process's
fan-out (filtered per screen, bounded, a resync for a screen that fell behind)."""

import asyncio
import json
from dataclasses import replace

import pytest
from ashley import logs
from ashley.live import live
from ashley.live.events import (BenchCued, DeviceViewer, HerState, HerStateName, Shown, ThreadTurn, Viewer, decode, encode,
                                shown_for, shown_to)
from ashley.live.fanout import RESYNC, Fanout

ALANA = Viewer(household_id=1, person_id=10)
SAM = Viewer(household_id=1, person_id=11)
NEIGHBOUR = Viewer(household_id=2, person_id=20)


def state(shown: Shown, turn: str = "t1", now: HerStateName = "thinking") -> HerState:
    return HerState(shown, turn, now, 180.0)


def test_an_owner_channel_is_its_person_only_and_a_shared_one_the_households() -> None:
    assert shown_for(True, 1, 10) == Shown(1, 10)
    assert shown_for(False, 1, 10) == Shown(1, None)
    assert shown_for(False, 1, None) == Shown(1, None)
    assert shown_for(True, 1, None) is None


@pytest.mark.parametrize(("shown", "seen_by"), [
    (Shown(1, None), {ALANA, SAM}),
    (Shown(1, 10), {ALANA}),
    (Shown(2, None), {NEIGHBOUR}),
    (Shown(2, 10), set[Viewer]()),
])
def test_an_event_is_shown_to_exactly_who_its_shown_names(shown: Shown, seen_by: set[Viewer]) -> None:
    assert {v for v in (ALANA, SAM, NEIGHBOUR) if shown_to(state(shown), v)} == seen_by


HALL = DeviceViewer(household_id=1, device_id=7)
DEN = DeviceViewer(household_id=1, device_id=8)
ELSEWHERE = DeviceViewer(household_id=2, device_id=7)


@pytest.mark.parametrize(("shown", "seen_by"), [
    (Shown(1, None), {HALL, DEN}),
    (Shown(1, None, 7), {HALL}),
    (Shown(1, 10), set[DeviceViewer]()),
    (Shown(2, None), {ELSEWHERE}),
    (Shown(2, 10), set[DeviceViewer]()),
])
def test_a_device_is_shown_shared_events_and_its_own_never_a_persons_or_another_households(
        shown: Shown, seen_by: set[DeviceViewer]) -> None:
    assert {d for d in (HALL, DEN, ELSEWHERE) if shown_to(state(shown), d)} == seen_by


def test_an_event_for_a_device_is_not_shown_to_any_person() -> None:
    assert not any(shown_to(ThreadTurn(Shown(1, None, 7), "device:7"), v) for v in (ALANA, SAM, NEIGHBOUR))


def test_an_event_names_a_person_or_a_device_not_both() -> None:
    with pytest.raises(ValueError):
        Shown(1, 10, 7)


def test_a_threads_turn_must_name_its_owner() -> None:
    with pytest.raises(ValueError):
        ThreadTurn(Shown(1, None), "person:10:web")


@pytest.mark.parametrize("event", [state(Shown(1, None)), state(Shown(1, 10), now="idle"),
                                   ThreadTurn(Shown(1, 10), "person:10:web"),
                                   ThreadTurn(Shown(1, None, 7), "device:7")])
def test_an_event_survives_the_wire_between_pods(event: HerState | ThreadTurn) -> None:
    assert decode(encode(event)) == event


@pytest.mark.parametrize("payload", ["", "{}", "[1]", '{"type": "state", "household_id": 1, "person_id": null}',
                                     '{"type": "state", "household_id": 1, "person_id": null, "turn": "t", '
                                     '"state": "dancing", "at_most_s": 1}',
                                     '{"type": "turn", "household_id": 1, "person_id": null, "thread": "device:7"}',
                                     '{"type": "other", "household_id": 1, "person_id": 1}'])
def test_a_malformed_payload_decodes_to_nothing(payload: str) -> None:
    assert decode(payload) is None


def test_the_wire_carries_no_text_room_or_speaker() -> None:
    assert set(json.loads(encode(state(Shown(1, None))))) == {
        "type", "household_id", "person_id", "device_id", "turn", "state", "at_most_s"}
    assert set(json.loads(encode(ThreadTurn(Shown(1, 10), "person:10:web")))) == {
        "type", "household_id", "person_id", "device_id", "thread"}


async def _drain(fanout: Fanout, viewer: Viewer, feed: list[HerState | ThreadTurn | None]) -> list[object]:
    got: list[object] = []
    async with fanout.subscription(viewer) as subscription:
        for event in feed:
            if event is None:
                fanout.resync()
            else:
                fanout.deliver(event)
        while (item := await subscription.next(0.01)) is not None:
            got.append(item)
    return got


def test_a_screen_gets_only_what_its_viewer_may_see_in_order() -> None:
    mine, theirs, house = state(Shown(1, 10), "a"), state(Shown(1, 11), "b"), state(Shown(1, None), "c")
    got = asyncio.run(_drain(Fanout(8), ALANA, [mine, theirs, house, None]))
    assert got == [mine, house, RESYNC]


def test_a_screen_that_falls_behind_drops_what_waits_for_one_resync(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    feed = [state(Shown(1, None), str(n)) for n in range(7)]
    got = asyncio.run(_drain(Fanout(3), ALANA, list(feed)))
    assert got == [RESYNC, feed[5], feed[6]]
    out = capsys.readouterr().out
    assert "event=live.closed" in out and "person=10" in out and "sent=3" in out and "dropped=5" in out


def test_a_screen_that_left_gets_nothing_more() -> None:
    async def scenario() -> int:
        fanout = Fanout(4)
        async with fanout.subscription(ALANA):
            assert len(fanout) == 1
        return fanout.deliver(state(Shown(1, None)))

    assert asyncio.run(scenario()) == 0


def test_the_shipped_tunables_load_and_bad_ones_are_refused() -> None:
    config = live.load()
    assert config.heartbeat_s < 125 and config.queue_size >= 2
    with pytest.raises(ValueError):
        replace(config, queue_size=1)
    with pytest.raises(ValueError):
        replace(config, heartbeat_s=0)


def test_a_bench_cue_survives_the_wire_and_is_shown_to_its_owner_alone() -> None:
    cue = BenchCued(Shown(1, 10), 5, 2, "seek", 61.5)
    assert decode(encode(cue)) == cue
    assert shown_to(cue, Viewer(1, 10)) and not shown_to(cue, Viewer(1, 11)) and not shown_to(cue, DeviceViewer(1, 7))
    with pytest.raises(ValueError):
        BenchCued(Shown(1, None), 5, 2, "play", None)
    assert decode(encode(cue).replace('"seek"', '"rewind"')) is None
