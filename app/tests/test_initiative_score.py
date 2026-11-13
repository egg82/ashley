"""The initiative score over its inputs, the seeded roll, the plan it makes, and the weights loader's refusals
(`ashley.initiative.score`, `ashley.initiative.weights`). Each weight is tested alone, every other one zero, so a
weight wired to the wrong fact or with its sign flipped moves the wrong case."""

import json
from pathlib import Path
from typing import Any

import pytest
from ashley.inference.reply import Reply
from ashley.initiative.initiative import NullInitiative, Scored
from ashley.initiative.moment import Moment
from ashley.initiative.score import planned, roll, score
from ashley.initiative.weights import FILE, WEIGHTS, Weights, load, parse
from initiative_support import weights

WORTH = Reply(spoken="Hi.", text="Hi.", says="reply")
OFFER = Reply(spoken="Hi.", text="Hi.", says="offer")
NOT_WORTH = Reply(spoken="Hi.", text="Hi.", says="none")


def only(key: str, weight: float, threshold: float = 0.0, **span: Any) -> Weights:
    """Every weight zero but `key`'s; odds all full above `threshold`."""
    raw = weights(threshold=threshold, odds=[{"from": threshold, "full": 1.0, "short": 0.0, "silent": 0.0}])
    raw[key] = {**raw[key], "weight": weight, **span}
    return parse(raw)


def at(**facts: Any) -> Moment:
    return Moment("wake:1", **facts)


# ---- the score over each input


def test_an_unknown_moment_scores_nothing() -> None:
    assert score(at(), WEIGHTS) == 0.0


def test_longer_since_she_heard_from_them_raises_the_score_up_to_its_span() -> None:
    w = only("heard", 2.0, full_at_s=1000)
    assert score(at(since_heard_s=0), w) == 0.0
    assert score(at(since_heard_s=500), w) == pytest.approx(1.0)
    assert score(at(since_heard_s=1000), w) == pytest.approx(2.0)
    assert score(at(since_heard_s=5000), w) == pytest.approx(2.0)


def test_the_night_lowers_the_score_only_inside_its_hours_across_midnight() -> None:
    w = only("night", -1.5, from_hour=22, to_hour=7)
    assert [score(at(hour=h), w) for h in (21, 22, 23, 0, 6, 7, 12)] == [0.0, -1.5, -1.5, -1.5, -1.5, 0.0, 0.0]


def test_a_night_that_does_not_cross_midnight() -> None:
    w = only("night", -1.0, from_hour=1, to_hour=5)
    assert [score(at(hour=h), w) for h in (0, 1, 4, 5)] == [0.0, -1.0, -1.0, 0.0]


def test_others_at_home_lower_the_score_up_to_the_cap() -> None:
    w = only("others_home", -0.3, cap=3)
    assert [round(score(at(others_home=n), w), 6) for n in (0, 1, 3, 9)] == [0.0, -0.1, -0.3, -0.3]


def test_a_recent_greeting_lowers_the_score_and_fades_over_its_window() -> None:
    w = only("greeted", -3.0, within_s=3600)
    assert score(at(since_greeted_s=0), w) == pytest.approx(-3.0)
    assert score(at(since_greeted_s=1800), w) == pytest.approx(-1.5)
    assert score(at(since_greeted_s=3600), w) == 0.0
    assert score(at(since_greeted_s=-5), w) == pytest.approx(-3.0)


def test_a_recent_word_of_hers_lowers_the_score_and_fades_over_its_window() -> None:
    w = only("spoke", -1.0, within_s=100)
    assert score(at(since_spoke_s=25), w) == pytest.approx(-0.75)
    assert score(at(since_spoke_s=100), w) == 0.0


def test_each_fact_moves_only_its_own_weight() -> None:
    w = only("greeted", -3.0, within_s=3600)
    assert score(at(since_spoke_s=0, since_heard_s=0, hour=23, others_home=3), w) == 0.0


def test_a_recent_greeting_silences_a_moment_that_would_speak() -> None:
    w = parse(weights(threshold=0.0, greeted={"weight": -3.0, "within_s": 3600},
                      odds=[{"from": 0.0, "full": 1.0, "short": 0.0, "silent": 0.0}]))
    assert planned(at(), w).outcome == "full", "control: with no greeting the moment speaks"
    got = planned(at(since_greeted_s=60), w)
    assert got.outcome == "silent" and got.roll is None
    assert Scored(w).speaks(WORTH, at(since_greeted_s=60)) is False
    assert Scored(w).speaks(WORTH, at()) is True


def test_the_shipped_weights_silence_a_greeting_a_minute_after_the_last() -> None:
    assert planned(at(since_greeted_s=60), WEIGHTS).outcome == "silent"
    assert planned(at(hour=3), WEIGHTS).outcome == "silent"
    assert planned(at(since_heard_s=86400, hour=18, others_home=0), WEIGHTS).roll is not None


# ---- the roll and the plan


def test_the_roll_is_fixed_by_its_seed() -> None:
    assert roll("wake:7") == roll("wake:7")
    assert roll("wake:7") != roll("wake:8")
    assert 0.0 <= roll("wake:7") < 1.0


def test_the_roll_is_this_exact_number_in_every_process() -> None:
    assert round(roll("wake:1"), 12) == round(int.from_bytes(
        __import__("hashlib").sha256(b"initiative:wake:1").digest()[:8], "big") / 2**64, 12)


def test_the_rolls_follow_the_odds_of_the_band() -> None:
    w = parse(weights(threshold=0.0, odds=[{"from": 0.0, "full": 0.5, "short": 0.3, "silent": 0.2}]))
    outcomes = [planned(Moment(f"wake:{i}"), w).outcome for i in range(4000)]
    assert outcomes.count("full") / 4000 == pytest.approx(0.5, abs=0.03)
    assert outcomes.count("short") / 4000 == pytest.approx(0.3, abs=0.03)
    assert outcomes.count("silent") / 4000 == pytest.approx(0.2, abs=0.03)


def test_the_same_wake_plans_the_same_every_time() -> None:
    m = at(since_heard_s=4000, hour=19, others_home=1)
    assert len({planned(m, WEIGHTS) for _ in range(20)}) == 1


def test_a_higher_score_rolls_against_its_own_band() -> None:
    w = parse(weights(threshold=0.0, heard={"weight": 1.0, "full_at_s": 100},
                      odds=[{"from": 0.0, "full": 0.0, "short": 1.0, "silent": 0.0},
                            {"from": 0.5, "full": 1.0, "short": 0.0, "silent": 0.0}]))
    assert planned(at(since_heard_s=10), w).outcome == "short"
    assert planned(at(since_heard_s=50), w).outcome == "full"
    assert planned(at(since_heard_s=100), w).outcome == "full"


def test_a_score_on_the_threshold_clears_it() -> None:
    w = parse(weights(threshold=0.0, odds=[{"from": 0.0, "full": 1.0, "short": 0.0, "silent": 0.0}]))
    assert planned(at(), w).outcome == "full"


def test_the_roll_picks_short_between_full_and_silent() -> None:
    seeds = {planned(Moment(f"wake:{i}"), parse(weights(
        threshold=0.0, odds=[{"from": 0.0, "full": 0.4, "short": 0.4, "silent": 0.2}]))).outcome: roll(f"wake:{i}")
        for i in range(200)}
    assert seeds["full"] < 0.4 <= seeds["short"] < 0.8 <= seeds["silent"]


# ---- the policy


def test_a_turn_with_no_moment_goes_out_on_her_says_alone() -> None:
    assert Scored(WEIGHTS).speaks(WORTH, None) is True and Scored(WEIGHTS).speaks(NOT_WORTH, None) is False
    assert Scored(WEIGHTS).speaks(OFFER, None) is True


def test_nothing_goes_out_that_she_says_none_to_whatever_the_moment() -> None:
    w = parse(weights())
    assert Scored(w).speaks(WORTH, at()) is True, "control: this moment lets a reply out"
    assert Scored(w).speaks(OFFER, at()) is True
    assert Scored(w).speaks(NOT_WORTH, at()) is False


def test_the_unwired_policy_plans_silence() -> None:
    assert NullInitiative().planned(at()).outcome == "silent" and NullInitiative().speaks(WORTH, at()) is False


# ---- the loader


def test_the_shipped_file_loads() -> None:
    assert load(FILE) == WEIGHTS and WEIGHTS.bands[0].start == WEIGHTS.threshold


def test_the_test_weights_load() -> None:
    assert parse(weights()).threshold < 0


def _bad(**changed: Any) -> dict[str, Any]:
    return weights(**changed)


@pytest.mark.parametrize("raw", [
    pytest.param([], id="not-an-object"),
    pytest.param({k: v for k, v in weights().items() if k != "spoke"}, id="missing-key"),
    pytest.param({**weights(), "mood": 1}, id="unknown-key"),
    pytest.param(_bad(heard={"weight": 1.0}), id="missing-span"),
    pytest.param(_bad(heard={"weight": -0.5, "full_at_s": 10}), id="heard-lowers"),
    pytest.param(_bad(night={"weight": 0.5, "from_hour": 22, "to_hour": 7}), id="night-raises"),
    pytest.param(_bad(others_home={"weight": 0.1, "cap": 3}), id="others-raise"),
    pytest.param(_bad(greeted={"weight": 1.0, "within_s": 60}), id="greeting-raises"),
    pytest.param(_bad(spoke={"weight": 1.0, "within_s": 60}), id="spoke-raises"),
    pytest.param(_bad(greeted={"weight": -1.0, "within_s": 0}), id="zero-window"),
    pytest.param(_bad(night={"weight": -1.0, "from_hour": 24, "to_hour": 7}), id="hour-off-clock"),
    pytest.param(_bad(night={"weight": -1.0, "from_hour": 22.5, "to_hour": 7}), id="fractional-hour"),
    pytest.param(_bad(others_home={"weight": -0.1, "cap": 0}), id="zero-cap"),
    pytest.param(_bad(threshold=True), id="bool-threshold"),
    pytest.param(_bad(threshold="0"), id="string-threshold"),
    pytest.param(_bad(threshold=float("nan")), id="nan-threshold"),
    pytest.param(_bad(odds=[]), id="no-bands"),
    pytest.param(_bad(odds=[{"from": 0.0, "full": 1.0, "short": 0.0, "silent": 0.0}]), id="band-above-threshold"),
    pytest.param(_bad(odds=[{"from": -1e9, "full": 0.5, "short": 0.4, "silent": 0.0}]), id="odds-under-one"),
    pytest.param(_bad(odds=[{"from": -1e9, "full": 1.2, "short": -0.2, "silent": 0.0}]), id="negative-odds"),
    pytest.param(_bad(odds=[{"from": -1e9, "full": 1.0, "short": 0.0, "silent": 0.0},
                            {"from": -1e9, "full": 1.0, "short": 0.0, "silent": 0.0}]), id="bands-not-rising"),
    pytest.param(_bad(odds=[{"from": -1e9, "full": 1.0, "short": 0.0}]), id="band-missing-outcome"),
])
def test_the_loader_refuses(raw: Any) -> None:
    with pytest.raises(ValueError):
        parse(raw)


def test_the_loader_refuses_a_file_that_is_not_json(tmp_path: Path) -> None:
    bad = tmp_path / "score.json"
    bad.write_text("{")
    with pytest.raises(ValueError):
        load(bad)
    bad.write_text(json.dumps(weights()))
    assert load(bad) == parse(weights()), "control: the same file with good weights loads"
