"""The voice adapter's tunables, as data in `voice.json` beside this module, validated when loaded.

`end_of_speech` decides when the person has stopped, as Home Assistant's own segmenter does: before the utterance a
10 ms frame is speech when the VAD's probability is above `start_probability`, and the utterance starts once
`speech_ms` of such frames have come with no run of `start_gap_ms` of non-speech between them; once started a frame is
speech above `speech_probability`, and the utterance ends after `silence_ms` of unbroken non-speech. It ends
regardless `max_utterance_ms` after the wake. `clip_retention_s` is how long a reply's
clip URL can be fetched. A satellite connection gives up a connect attempt after `connect_timeout_s` and retries after
a backoff doubling from `reconnect_first_s` to `reconnect_max_s`; the list of satellites is re-read every
`satellites_poll_s`. `speaker` is the voice match's `heard_as.MatchPolicy`, and `enrol_minutes` how long an enrolment
the admin CLI arms lasts when it is not told. `playback` estimates how long a reply plays (`Playback`)."""

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .heard_as import MatchPolicy

FILE = Path(__file__).with_name("voice.json")


@dataclass(frozen=True)
class EndOfSpeech:
    start_probability: float
    speech_probability: float
    speech_ms: int
    start_gap_ms: int
    silence_ms: int
    max_utterance_ms: int

    def __post_init__(self) -> None:
        if not (0 < self.start_probability < 1 and 0 < self.speech_probability < 1):
            raise ValueError("end_of_speech probabilities must be between 0 and 1")
        if min(self.speech_ms, self.silence_ms, self.start_gap_ms) <= 0:
            raise ValueError("end_of_speech.speech_ms, start_gap_ms and silence_ms must be positive")
        if self.max_utterance_ms <= self.speech_ms + self.silence_ms:
            raise ValueError("end_of_speech.max_utterance_ms must leave room for speech and the silence after it")


@dataclass(frozen=True)
class Playback:
    """How long her reply plays, estimated because neither a satellite nor a room speaker reports its end: `lead_s`
    from the URL being handed over to the first sound, then `words_per_s` of her words."""

    lead_s: float
    words_per_s: float

    def __post_init__(self) -> None:
        if self.lead_s < 0 or self.words_per_s <= 0:
            raise ValueError("playback.lead_s must not be negative and playback.words_per_s must be positive")

    def seconds(self, text: str) -> float:
        return self.lead_s + len(text.split()) / self.words_per_s


@dataclass(frozen=True)
class Config:
    end_of_speech: EndOfSpeech
    clip_retention_s: int
    connect_timeout_s: float
    reconnect_first_s: float
    reconnect_max_s: float
    satellites_poll_s: float
    speaker: MatchPolicy
    enrol_minutes: float
    playback: Playback

    def __post_init__(self) -> None:
        if min(self.clip_retention_s, self.connect_timeout_s, self.reconnect_first_s, self.satellites_poll_s,
               self.enrol_minutes) <= 0:
            raise ValueError("voice timings must be positive")
        if self.reconnect_max_s < self.reconnect_first_s:
            raise ValueError("reconnect_max_s must be at least reconnect_first_s")


def parse(raw: dict[str, Any]) -> Config:
    """A Config from the decoded JSON. Raises ValueError naming a key that is missing, unknown or out of range."""
    _keys(raw, {f.name for f in fields(Config)}, "voice.json")
    eos: dict[str, Any] = raw["end_of_speech"]
    _keys(eos, {f.name for f in fields(EndOfSpeech)}, "end_of_speech")
    playback: dict[str, Any] = raw["playback"]
    _keys(playback, {f.name for f in fields(Playback)}, "playback")
    _numbers(playback, "playback")
    rest = {k: v for k, v in raw.items() if k not in ("end_of_speech", "speaker", "playback")}
    _numbers(eos, "end_of_speech")
    _numbers(rest, "voice.json")
    return Config(end_of_speech=EndOfSpeech(**eos), speaker=_speaker(raw["speaker"]), playback=Playback(**playback),
                  **rest)


def _speaker(raw: dict[str, Any]) -> MatchPolicy:
    _keys(raw, {f.name for f in fields(MatchPolicy)}, "speaker")
    _numbers({k: v for k, v in raw.items() if k != "decides"}, "speaker")
    if not isinstance(raw["decides"], bool):
        raise ValueError("speaker.decides must be true or false")
    if isinstance(raw["min_audio_ms"], float) or raw["min_audio_ms"] <= 0:
        raise ValueError("speaker.min_audio_ms must be a positive whole number")
    if not (-1 <= raw["floor"] <= 1 and 0 <= raw["margin"] <= 2):
        raise ValueError("speaker.floor must be in [-1, 1] and speaker.margin in [0, 2]")
    return MatchPolicy(**raw)


def _keys(values: dict[str, Any], expected: set[str], where: str) -> None:
    if set(values) != expected:
        raise ValueError(f"{where} keys: missing {sorted(expected - set(values))}, "
                         f"unknown {sorted(set(values) - expected)}")


def _numbers(values: dict[str, Any], where: str) -> None:
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{where}.{key} must be a number")


def load(path: Path = FILE) -> Config:
    return parse(json.loads(path.read_text(encoding="utf-8")))
