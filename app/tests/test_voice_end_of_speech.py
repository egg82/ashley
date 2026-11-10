"""End of speech as 10 ms frames, the voice tunables as validated data, and the pronunciation lexicon."""

import json
from typing import Any

import pytest
from ashley.channels.lexicon import Lexicon
from ashley.channels.voice import config
from ashley.channels.voice.config import EndOfSpeech
from ashley.channels.voice.end_of_speech import State, Utterance

TIMINGS = EndOfSpeech(start_probability=0.2, speech_probability=0.5, speech_ms=30, start_gap_ms=50, silence_ms=50,
                      max_utterance_ms=1000)
SPEECH, QUIET = 0.9, 0.1


def states(probabilities: list[float], timings: EndOfSpeech = TIMINGS) -> list[State]:
    utterance = Utterance(timings)
    return [utterance.frame(p) for p in probabilities]


def test_speech_starts_after_speech_ms_in_a_row_and_ends_after_silence_ms_in_a_row() -> None:
    got = states([SPEECH] * 3 + [QUIET] * 5)
    assert got == ["waiting", "waiting", "speaking"] + ["speaking"] * 4 + ["ended"]


def test_a_short_gap_before_the_start_keeps_the_count_and_a_long_one_starts_it_again() -> None:
    assert states([SPEECH, SPEECH, QUIET, SPEECH])[-1] == "speaking"
    assert states([SPEECH, SPEECH] + [QUIET] * 4 + [SPEECH])[-1] == "speaking"
    assert states([SPEECH, SPEECH] + [QUIET] * 5 + [SPEECH, SPEECH])[-1] == "waiting"
    assert states([SPEECH, SPEECH] + [QUIET] * 5 + [SPEECH] * 3)[-1] == "speaking"


def test_faint_speech_starts_the_utterance_but_does_not_hold_it_open() -> None:
    faint = 0.3   # above start_probability, below speech_probability
    assert states([faint] * 3)[-1] == "speaking"
    assert states([faint] * 3 + [faint] * 5)[-1] == "ended"
    assert states([faint] * 3 + [SPEECH] * 5)[-1] == "speaking"


def test_speech_inside_the_silence_window_keeps_the_utterance_going() -> None:
    got = states([SPEECH] * 3 + [QUIET] * 4 + [SPEECH] + [QUIET] * 4)
    assert "ended" not in got


def test_the_threshold_is_exclusive_and_a_warming_vad_is_not_speech() -> None:
    assert states([0.2] * 10)[-1] == "waiting"
    assert states([-1.0] * 10)[-1] == "waiting"


def test_it_ends_at_the_maximum_whatever_is_heard() -> None:
    short = EndOfSpeech(start_probability=0.2, speech_probability=0.5, speech_ms=30, start_gap_ms=50, silence_ms=50,
                        max_utterance_ms=100)
    assert states([QUIET] * 10, short)[-1] == "ended" and states([QUIET] * 9, short)[-1] == "waiting"
    assert states([SPEECH] * 10, short)[-1] == "ended"


def test_ended_is_final() -> None:
    assert states([SPEECH] * 3 + [QUIET] * 5 + [SPEECH] * 5)[-1] == "ended"


def test_the_shipped_voice_json_loads_with_700_ms_of_silence() -> None:
    assert config.load().end_of_speech.silence_ms == 700


def shipped() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(config.FILE.read_text(encoding="utf-8"))
    return raw


GONE = object()


@pytest.mark.parametrize(("nested", "key", "value"), [
    (False, "clip_retention_s", GONE),
    (False, "extra", 1),
    (True, "silence_ms", GONE),
    (True, "speech_probability", 1.5),
    (True, "start_probability", 0),
    (True, "start_gap_ms", 0),
    (True, "silence_ms", 0),
    (True, "max_utterance_ms", 500),
    (True, "speech_ms", "300"),
    (False, "clip_retention_s", True),
    (False, "reconnect_max_s", 0.5),
    (False, "satellites_poll_s", -1),
])
def test_a_bad_voice_json_is_refused(nested: bool, key: str, value: object) -> None:
    raw = shipped()
    assert config.parse(raw).clip_retention_s > 0, "control: the shipped file parses"
    target: dict[str, Any] = raw["end_of_speech"] if nested else raw
    if value is GONE:
        del target[key]
    else:
        target[key] = value
    with pytest.raises(ValueError):
        config.parse(raw)


def test_a_lexicon_respells_whole_words() -> None:
    said = Lexicon({"Mochi": "Mowchi"}).respell("Mochi is asleep; Mochi's bowl is full. Mochiville and MOCHI stay.")
    assert said == "Mowchi is asleep; Mowchi's bowl is full. Mochiville and MOCHI stay."


@pytest.mark.parametrize("bad", [{"two words": "x"}, {"Mochi": " "}, {"": "x"}, {"Mochi": "x" * 65}])
def test_a_bad_lexicon_entry_is_refused(bad: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Lexicon(bad)
