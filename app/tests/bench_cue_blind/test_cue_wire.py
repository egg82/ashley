"""A cue on the wire: the command and effect round trip through the codec, `BenchCued` is shown to its owner's screens
alone, survives the pod-to-pod encoding, and reaches a screen as the `cue` event of `LiveCue`."""

import json

import pytest
from ashley.api.live import frame, wire
from ashley.api.live_models import LiveCue, LiveEvent
from ashley.live.events import BenchChanged, BenchCued, CueName, DeviceViewer, Shown, Viewer, decode, encode, shown_to
from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import Cue, CueAction, Cued, type_of
from ashley.workshop.model import HER, By

ALANA = Viewer(1, 10)
SAM = Viewer(1, 11)
NEIGHBOUR = Viewer(2, 10)
CUES = [("play", None), ("pause", None), ("seek", 0.0), ("seek", 61.5), ("seek", 359_999.0)]


@pytest.mark.parametrize(("action", "seconds"), CUES)
@pytest.mark.parametrize("by", [HER, By(10)])
def test_a_cue_command_round_trips_through_the_codec(action: CueAction, seconds: float | None, by: By) -> None:
    command = Cue(by, 4, action, seconds)
    raw = encode_command(command)
    assert raw["type"] == type_of(command) == "cue"
    assert decode_command(json.loads(json.dumps(raw)), by) == command


@pytest.mark.parametrize(("action", "seconds"), CUES)
def test_a_cued_effect_round_trips_through_the_codec(action: CueAction, seconds: float | None) -> None:
    effect = Cued(4, action, seconds)
    assert decode_effect(json.loads(json.dumps(encode_effect(effect)))) == effect


def test_a_cued_effect_keeps_its_piece_and_a_seek_its_seconds_apart_from_a_play() -> None:
    a = encode_effect(Cued(3, "seek", 7.0))
    b = encode_effect(Cued(3, "play", None))
    assert a != b and decode_effect(a) != decode_effect(b)
    assert decode_effect(encode_effect(Cued(3, "play", None))) == Cued(3, "play", None)
    assert decode_effect(encode_effect(Cued(4, "play", None))) != Cued(3, "play", None)


# --- who is shown a cue -------------------------------------------------------------------------------------------


def test_a_cue_is_shown_to_the_owners_screens_and_no_one_elses() -> None:
    event = BenchCued(Shown(1, 10), 5, 2, "seek", 61.5)
    assert shown_to(event, ALANA)
    assert not shown_to(event, SAM)
    assert not shown_to(event, NEIGHBOUR)
    assert not shown_to(event, DeviceViewer(1, 3))


@pytest.mark.parametrize("shown", [Shown(1, None), Shown(1, None, 3)])
def test_a_cue_for_no_person_is_refused(shown: Shown) -> None:
    with pytest.raises(ValueError):
        BenchCued(shown, 5, 2, "play", None)


@pytest.mark.parametrize(("action", "seconds"), CUES)
def test_a_cue_survives_the_wire_between_pods(action: CueName, seconds: float | None) -> None:
    event = BenchCued(Shown(1, 10), 5, 2, action, seconds)
    assert decode(encode(event)) == event


def test_a_cue_is_not_decoded_as_a_bench_change_and_a_change_not_as_a_cue() -> None:
    cued = decode(encode(BenchCued(Shown(1, 10), 5, 2, "play", None)))
    changed = decode(encode(BenchChanged(Shown(1, 10), 5, 2)))
    assert isinstance(cued, BenchCued) and not isinstance(cued, BenchChanged)
    assert isinstance(changed, BenchChanged)


@pytest.mark.parametrize("action", ["rewind", "", "SEEK", None])
def test_a_cue_payload_with_an_unknown_action_decodes_to_nothing(action: object) -> None:
    payload = json.loads(encode(BenchCued(Shown(1, 10), 5, 2, "play", None)))
    payload["action"] = action
    assert decode(json.dumps(payload)) is None


def test_a_cue_payload_missing_its_piece_decodes_to_nothing() -> None:
    payload = json.loads(encode(BenchCued(Shown(1, 10), 5, 2, "play", None)))
    del payload["piece_id"]
    assert decode(json.dumps(payload)) is None


# --- what a screen reads ------------------------------------------------------------------------------------------


def test_a_screen_reads_a_cue_as_the_cue_event_not_a_bench_change() -> None:
    got = wire(BenchCued(Shown(1, 10), 5, 2, "seek", 61.5))
    assert isinstance(got.root, LiveCue)
    assert (got.root.type, got.root.bench_id, got.root.piece_id, got.root.action, got.root.seconds) == (
        "cue", 5, 2, "seek", 61.5)


def test_a_play_cue_on_the_wire_has_null_seconds() -> None:
    sent = json.loads(frame(BenchCued(Shown(1, 10), 5, 2, "play", None)).removeprefix(b"data: "))
    assert sent == {"type": "cue", "bench_id": 5, "piece_id": 2, "action": "play", "seconds": None}


def test_the_cue_event_is_part_of_the_live_event_union() -> None:
    parsed = LiveEvent.model_validate({"type": "cue", "bench_id": 1, "piece_id": 2, "action": "pause", "seconds": None})
    assert isinstance(parsed.root, LiveCue)
    with pytest.raises(ValueError):
        LiveEvent.model_validate({"type": "cue", "bench_id": 1, "piece_id": 2, "action": "rewind", "seconds": None})


def test_a_bench_change_is_still_a_bench_event_on_the_wire() -> None:
    sent = json.loads(frame(BenchChanged(Shown(1, 10), 5, 7)).removeprefix(b"data: "))
    assert sent == {"type": "bench", "bench_id": 5, "seq": 7, "by": None}
