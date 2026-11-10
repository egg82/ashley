"""`match`'s order of outcomes and presence agreement, and the `speaker` block of `voice.json`."""

import copy
import json
from typing import Any

import pytest
from ashley.channels.voice import config
from ashley.channels.voice.heard_as import MatchPolicy, match
from ashley.channels.voice.voices import PersonPrints
from ashley.inference.voiceprint import Voiceprint

POLICY = MatchPolicy(floor=0.5, margin=0.1, min_audio_ms=1000, decides=True)
ALANA = PersonPrints(1, ((1.0, 0.0, 0.0), (0.8, 0.6, 0.0)))
SAM = PersonPrints(2, ((0.0, 1.0, 0.0),))


def heard(vector: tuple[float, ...], audio_ms: int = 1500) -> Voiceprint:
    return Voiceprint(vector, "titanet", audio_ms)


def test_the_closest_person_home_is_matched_and_presence_agrees() -> None:
    m = match(heard((1.0, 0.0, 0.0)), (ALANA, SAM), frozenset({1}), POLICY)
    assert (m.outcome, m.person_id, m.presence) == ("matched", 1, "yes")
    assert m.best is not None and m.second is not None
    assert m.best == pytest.approx(0.9 / (0.9 ** 2 + 0.3 ** 2) ** 0.5), "against the renormalised mean"
    assert m.second == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("vector, prints, home, audio_ms, outcome, presence", [
    ((1.0, 0.0, 0.0), (ALANA, SAM), frozenset({1}), 999, "too_short", "no"),
    ((1.0, 0.0, 0.0), (), None, 1500, "no_prints", "unknown"),
    ((0.0, 0.0, 1.0), (ALANA, SAM), frozenset({1, 2}), 1500, "below_floor", "unknown"),
    ((0.585, 0.811, 0.0), (ALANA, SAM), None, 1500, "close_second", "unknown"),
    ((1.0, 0.0, 0.0), (ALANA, SAM), frozenset({2}), 1500, "away", "no"),
    ((1.0, 0.0, 0.0), (ALANA, SAM), frozenset[int](), 1500, "away", "unknown"),
])
def test_each_outcome_names_no_one(vector: tuple[float, ...], prints: tuple[PersonPrints, ...],
                                   home: frozenset[int] | None, audio_ms: int, outcome: str, presence: str) -> None:
    m = match(heard(vector, audio_ms), prints, home, POLICY)
    assert (m.outcome, m.person_id, m.presence) == (outcome, None, presence)


def test_too_short_scores_nothing_and_a_tie_is_a_close_second_at_any_margin() -> None:
    short = match(heard((1.0, 0.0, 0.0), 10), (ALANA,), None, POLICY)
    assert (short.best, short.second) == (None, None)
    twins = (PersonPrints(1, ((1.0, 0.0),)), PersonPrints(2, ((1.0, 0.0),)))
    zero = MatchPolicy(floor=0.5, margin=0.0, min_audio_ms=1, decides=True)
    assert match(heard((1.0, 0.0)), twins, None, zero).outcome == "close_second"
    assert match(heard((1.0, 0.0)), twins[:1], None, zero).outcome == "matched", "control: one print matches"


def test_a_print_of_another_length_is_refused() -> None:
    with pytest.raises(ValueError):
        match(heard((1.0, 0.0)), (ALANA,), None, POLICY)


def shipped() -> dict[str, Any]:
    return json.loads(config.FILE.read_text(encoding="utf-8"))


def test_the_shipped_speaker_block_only_logs() -> None:
    loaded = config.load()
    assert loaded.speaker == MatchPolicy(floor=0.5, margin=0.1, min_audio_ms=1000, decides=False)
    assert loaded.enrol_minutes == 30


@pytest.mark.parametrize("key, value", [
    ("floor", 1.5), ("floor", -1.01), ("margin", -0.1), ("margin", 2.5), ("min_audio_ms", 0),
    ("min_audio_ms", 1000.5), ("decides", "no"), ("decides", 1), ("floor", True), ("extra", 1),
])
def test_a_bad_speaker_block_is_refused(key: str, value: object) -> None:
    raw = shipped()
    assert config.parse(copy.deepcopy(raw)).speaker.floor == 0.5, "control: the shipped file parses"
    raw["speaker"][key] = value
    with pytest.raises(ValueError):
        config.parse(raw)


def test_enrol_minutes_must_be_positive() -> None:
    raw = shipped()
    raw["enrol_minutes"] = 0
    with pytest.raises(ValueError):
        config.parse(raw)
