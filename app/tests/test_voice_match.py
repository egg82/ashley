"""`heard_as.match`: whose voice an utterance is, from the household's prints and presence. Written from the interface
and `decisions.md` alone. Vectors are small and chosen so the cosines are exact: the utterance is (1, 0), so a unit
print's score is its first coordinate, and a mean's score is that coordinate over the mean's length."""

import math
from dataclasses import replace

import pytest
from ashley.channels.voice.heard_as import Agreement, Match, MatchPolicy, Outcome, match
from ashley.channels.voice.voices import PersonPrints
from ashley.inference.voiceprint import Voiceprint
from hypothesis import assume, given, settings
from hypothesis import strategies as st

MODEL = "titanet-small"
UTTERANCE = Voiceprint(vector=(1.0, 0.0), model=MODEL, audio_ms=2000)
POLICY = MatchPolicy(floor=0.5, margin=0.1, min_audio_ms=1000, decides=True)
A, B, C = 1, 2, 3
SAME = (1.0, 0.0)        # scores 1.0
ORTHOGONAL = (0.0, 1.0)  # scores 0.0
OPPOSITE = (-1.0, 0.0)   # scores -1.0
S8, S6 = (0.8, 0.6), (0.6, 0.8)  # unit vectors scoring 0.8 and 0.6


def one(person_id: int, *vectors: tuple[float, ...]) -> PersonPrints:
    return PersonPrints(person_id, tuple(vectors))


def run(*prints: PersonPrints, home: frozenset[int] | None = None, policy: MatchPolicy = POLICY,
        audio_ms: int = 2000, vector: tuple[float, ...] = UTTERANCE.vector) -> Match:
    return match(Voiceprint(vector, MODEL, audio_ms), tuple(prints), home, policy)


def test_a_clear_best_person_is_matched_with_both_scores() -> None:
    result = run(one(A, S8), one(B, S6))
    assert result.outcome == "matched" and result.person_id == A
    assert result.best == pytest.approx(0.8) and result.second == pytest.approx(0.6)


def test_the_best_is_found_whatever_order_the_people_arrive_in() -> None:
    forward = run(one(A, S6), one(B, S8), one(C, ORTHOGONAL))
    backward = run(one(C, ORTHOGONAL), one(B, S8), one(A, S6))
    assert forward == backward
    assert forward.person_id == B and forward.second == pytest.approx(0.6)


def test_only_one_person_has_a_best_and_no_second() -> None:
    result = run(one(A, S8))
    assert (result.outcome, result.person_id) == ("matched", A)
    assert result.best == pytest.approx(0.8) and result.second is None


def test_a_second_of_exactly_zero_is_a_score_not_an_absence() -> None:
    result = run(one(A, SAME), one(B, ORTHOGONAL))
    assert result.second is not None and result.second == pytest.approx(0.0)


def test_a_persons_score_is_the_cosine_with_the_renormalised_mean_of_their_prints() -> None:
    # Mean of (1,0) and (0,1) is (.5,.5): cosine .7071. The best single print would score 1.0; the unnormalised mean's
    # dot product would be .5, which is under this floor.
    result = run(one(A, SAME, ORTHOGONAL), policy=replace(POLICY, floor=0.6))
    assert result.outcome == "matched"
    assert result.best == pytest.approx(math.sqrt(0.5))


def test_the_centroid_picks_the_person_a_max_over_prints_would_not() -> None:
    # A's best single print scores 1.0 but their centroid .7071; B's one print scores .8. Centroid scoring names B.
    result = run(one(A, SAME, ORTHOGONAL), one(B, S8), policy=replace(POLICY, margin=0.05))
    assert (result.outcome, result.person_id) == ("matched", B)
    assert result.best == pytest.approx(0.8) and result.second == pytest.approx(math.sqrt(0.5))


def test_every_print_of_a_person_counts_equally_in_the_mean() -> None:
    # Three prints (1,0),(1,0),(0,1): mean (2/3,1/3) scores 2/sqrt(5); weighting only the first or last differs.
    result = run(one(A, SAME, SAME, ORTHOGONAL))
    assert result.best == pytest.approx(2 / math.sqrt(5))


def test_prints_that_differ_off_the_utterances_axis_average_out() -> None:
    # The mean of (.6,.8,0) and (.6,-.8,0) is (.6,0,0), which points the way the utterance does.
    result = run(one(A, (0.6, 0.8, 0.0), (0.6, -0.8, 0.0)), vector=(1.0, 0.0, 0.0))
    assert result.best == pytest.approx(1.0)


def test_a_negative_score_is_a_score() -> None:
    result = run(one(A, OPPOSITE), policy=replace(POLICY, floor=-1.0))
    assert (result.outcome, result.person_id) == ("matched", A)
    assert result.best == pytest.approx(-1.0)


def test_a_best_under_the_floor_is_below_floor_and_names_no_one() -> None:
    result = run(one(A, ORTHOGONAL), one(B, OPPOSITE))
    assert (result.outcome, result.person_id) == ("below_floor", None)
    assert result.best == pytest.approx(0.0) and result.second == pytest.approx(-1.0)


def test_a_best_exactly_at_the_floor_is_matched() -> None:
    assert run(one(A, SAME), policy=replace(POLICY, floor=1.0)).outcome == "matched"


def test_a_runner_up_inside_the_margin_is_close_second() -> None:
    result = run(one(A, S8), one(B, (0.75, math.sqrt(1 - 0.75 ** 2))))
    assert (result.outcome, result.person_id) == ("close_second", None)
    assert result.best == pytest.approx(0.8) and result.second == pytest.approx(0.75)


def test_a_lead_exactly_the_margin_is_matched_and_a_hair_under_is_not() -> None:
    people = (one(A, SAME), one(B, ORTHOGONAL))  # lead is exactly 1.0
    assert run(*people, policy=replace(POLICY, margin=1.0)).outcome == "matched"
    assert run(*people, policy=replace(POLICY, margin=1.0001)).outcome == "close_second"


def test_a_tie_for_best_is_close_second_even_with_a_zero_margin() -> None:
    result = run(one(A, S8), one(B, S8), policy=replace(POLICY, margin=0.0))
    assert (result.outcome, result.person_id) == ("close_second", None)
    assert result.best == pytest.approx(0.8) and result.second == pytest.approx(0.8)


def test_a_tie_is_close_second_wherever_the_tied_people_sit_in_the_list() -> None:
    tied = (one(C, S8), one(A, S6), one(B, S8))
    assert run(*tied, policy=replace(POLICY, margin=0.0)).outcome == "close_second"


def test_a_tie_under_the_floor_is_below_floor() -> None:
    assert run(one(A, ORTHOGONAL), one(B, ORTHOGONAL)).outcome == "below_floor"


def test_a_zero_margin_with_a_lead_is_matched() -> None:
    assert run(one(A, S8), one(B, S6), policy=replace(POLICY, margin=0.0)).outcome == "matched"


def test_audio_under_the_minimum_is_too_short_and_scores_nothing() -> None:
    result = run(one(A, SAME), one(B, S6), audio_ms=999)
    assert result == Match("too_short", None, None, None, "unknown")


def test_audio_at_the_minimum_is_long_enough() -> None:
    assert run(one(A, SAME), audio_ms=1000).outcome == "matched"


def test_too_short_outranks_no_prints() -> None:
    assert run(audio_ms=10).outcome == "too_short"


def test_nobody_with_prints_is_no_prints_with_nothing_scored() -> None:
    assert run() == Match("no_prints", None, None, None, "unknown")


def test_below_floor_outranks_close_second() -> None:
    assert run(one(A, ORTHOGONAL), one(B, (0.05, math.sqrt(1 - 0.05 ** 2)))).outcome == "below_floor"


def test_below_floor_outranks_away() -> None:
    assert run(one(A, ORTHOGONAL), home=frozenset({B})).outcome == "below_floor"


def test_close_second_outranks_away() -> None:
    result = run(one(A, S8), one(B, (0.75, math.sqrt(1 - 0.75 ** 2))), home=frozenset({B}))
    assert result.outcome == "close_second"


def test_a_best_who_is_not_home_is_away_and_names_no_one() -> None:
    result = run(one(A, S8), one(B, ORTHOGONAL), home=frozenset({B}))
    assert (result.outcome, result.person_id) == ("away", None)
    assert result.best == pytest.approx(0.8) and result.second == pytest.approx(0.0)


def test_a_best_who_is_home_is_matched_even_when_others_are_too() -> None:
    assert run(one(A, S8), one(B, ORTHOGONAL), home=frozenset({A, B})).person_id == A


def test_unknown_presence_never_makes_anyone_away() -> None:
    assert run(one(A, S8), home=None).outcome == "matched"


def test_known_but_empty_presence_makes_the_best_away() -> None:
    result = run(one(A, S8), home=frozenset())
    assert (result.outcome, result.presence) == ("away", "unknown")


def test_presence_is_the_best_persons_not_the_runner_ups() -> None:
    assert run(one(A, S8), one(B, ORTHOGONAL), home=frozenset({A})).outcome == "matched"


def test_a_match_for_the_one_person_home_agrees() -> None:
    assert run(one(A, S8), home=frozenset({A})).presence == "yes"


@pytest.mark.parametrize(("prints", "audio_ms", "outcome"), [
    ((one(A, S8),), 10, "too_short"),
    ((), 2000, "no_prints"),
    ((one(A, ORTHOGONAL),), 2000, "below_floor"),
    ((one(A, S8), one(B, S8)), 2000, "close_second"),
    ((one(B, S8),), 2000, "away"),
])
def test_naming_no_one_when_exactly_one_person_is_home_disagrees(
        prints: tuple[PersonPrints, ...], audio_ms: int, outcome: Outcome) -> None:
    result = run(*prints, home=frozenset({A}), audio_ms=audio_ms)
    assert (result.outcome, result.presence) == (outcome, "no")


@pytest.mark.parametrize("home", [None, frozenset[int](), frozenset({A, B}), frozenset({A, B, C})])
def test_presence_is_unknown_unless_exactly_one_person_is_home(home: frozenset[int] | None) -> None:
    result = run(one(A, S8), home=home)
    assert result.presence == "unknown"


def test_presence_is_unknown_for_every_outcome_when_two_are_home() -> None:
    home = frozenset({A, B})
    for prints, audio_ms in (((one(A, S8),), 10), ((), 2000), ((one(A, ORTHOGONAL),), 2000),
                             ((one(A, S8), one(B, S8)), 2000), ((one(A, S8),), 2000)):
        assert run(*prints, home=home, audio_ms=audio_ms).presence == "unknown"


def test_one_person_home_who_is_not_the_voice_disagrees_even_if_the_voice_is_away() -> None:
    assert run(one(A, S8), one(B, S6), home=frozenset({B})).presence == "no"


def test_a_print_of_the_wrong_length_raises() -> None:
    with pytest.raises(ValueError):
        run(one(A, (1.0, 0.0, 0.0)))
    with pytest.raises(ValueError):
        run(one(A, (1.0,)))


def test_a_wrong_length_print_raises_even_for_a_person_who_would_not_be_best() -> None:
    with pytest.raises(ValueError):
        run(one(A, SAME), one(B, (0.0, 0.0, 1.0)))
    with pytest.raises(ValueError):
        run(one(A, SAME), one(B, ORTHOGONAL, (0.0, 0.0, 1.0)))


@pytest.mark.parametrize(("prints", "home", "audio_ms"), [
    ((one(A, S8), one(B, S6)), None, 2000),
    ((one(A, S8), one(B, S6)), frozenset({B}), 2000),
    ((one(A, S8), one(B, S8)), frozenset({A}), 2000),
    ((one(A, ORTHOGONAL),), None, 2000),
    ((), None, 2000),
    ((one(A, S8),), None, 10),
])
def test_decides_is_only_for_the_caller_and_never_changes_the_result(
        prints: tuple[PersonPrints, ...], home: frozenset[int] | None, audio_ms: int) -> None:
    on = run(*prints, home=home, audio_ms=audio_ms, policy=replace(POLICY, decides=True))
    off = run(*prints, home=home, audio_ms=audio_ms, policy=replace(POLICY, decides=False))
    assert on == off


# Properties from the contract. Vectors have small non-negative integer coordinates so a mean is never zero; they are
# normalised here, as a Voiceprint's and a stored print's are.

COORDS = st.integers(min_value=0, max_value=6)


def unit(raw: tuple[int, ...]) -> tuple[float, ...]:
    length = math.sqrt(sum(c * c for c in raw))
    return tuple(c / length for c in raw)


def vectors(dim: int) -> st.SearchStrategy[tuple[float, ...]]:
    return st.tuples(*[COORDS] * dim).filter(lambda raw: any(raw)).map(unit)


@st.composite
def scenes(draw: st.DrawFn) -> tuple[Voiceprint, tuple[PersonPrints, ...], frozenset[int] | None, MatchPolicy]:
    dim = draw(st.integers(min_value=2, max_value=4))
    ids = draw(st.lists(st.integers(min_value=1, max_value=50), max_size=4, unique=True))
    prints = tuple(PersonPrints(i, tuple(draw(st.lists(vectors(dim), min_size=1, max_size=3)))) for i in ids)
    home = draw(st.none() | st.frozensets(st.integers(min_value=1, max_value=50), max_size=3))
    policy = MatchPolicy(floor=draw(st.floats(min_value=-1.0, max_value=1.0)),
                         margin=draw(st.floats(min_value=0.0, max_value=2.0)),
                         min_audio_ms=draw(st.integers(min_value=1, max_value=3000)), decides=draw(st.booleans()))
    voiceprint = Voiceprint(draw(vectors(dim)), MODEL, draw(st.integers(min_value=0, max_value=4000)))
    return voiceprint, prints, home, policy


def oracle_score(u: tuple[float, ...], mine: PersonPrints) -> float:
    mean = [sum(v[k] for v in mine.vectors) / len(mine.vectors) for k in range(len(u))]
    length = math.sqrt(sum(m * m for m in mean))
    return sum(a * m for a, m in zip(u, mean)) / length


def agreement(outcome: str, person_id: int | None, home: frozenset[int] | None) -> Agreement:
    if home is None or len(home) != 1:
        return "unknown"
    return "yes" if outcome == "matched" and person_id in home else "no"


@settings(max_examples=80, deadline=None)
@given(scenes())
def test_property_a_match_is_justified_by_the_contract(
        scene: tuple[Voiceprint, tuple[PersonPrints, ...], frozenset[int] | None, MatchPolicy]) -> None:
    voiceprint, prints, home, policy = scene
    result = match(voiceprint, prints, home, policy)
    assert (result.person_id is not None) == (result.outcome == "matched")
    if result.outcome == "matched":
        assert result.person_id in {p.person_id for p in prints}
        assert result.best is not None and result.best >= policy.floor
        assert result.second is None or (result.best - result.second >= policy.margin and result.best > result.second)
        assert home is None or result.person_id in home
        assert voiceprint.audio_ms >= policy.min_audio_ms
    if result.outcome in ("too_short", "no_prints"):
        assert result.best is None and result.second is None
    if result.outcome == "too_short":
        assert voiceprint.audio_ms < policy.min_audio_ms
    if result.outcome == "no_prints":
        assert not prints
    assert result.presence == agreement(result.outcome, result.person_id, home)


@settings(max_examples=80, deadline=None)
@given(scenes())
def test_property_scores_and_precedence_follow_the_stated_order(
        scene: tuple[Voiceprint, tuple[PersonPrints, ...], frozenset[int] | None, MatchPolicy]) -> None:
    voiceprint, prints, home, policy = scene
    result = match(voiceprint, prints, home, policy)
    if voiceprint.audio_ms < policy.min_audio_ms:
        assert result.outcome == "too_short"
        return
    if not prints:
        assert result.outcome == "no_prints"
        return
    scored = sorted(((oracle_score(voiceprint.vector, p), p.person_id) for p in prints), reverse=True)
    best, second = scored[0][0], (scored[1][0] if len(scored) > 1 else None)
    assert result.best == pytest.approx(best, abs=1e-9)
    assert (result.second is None) == (second is None)
    if second is not None:
        assert result.second == pytest.approx(second, abs=1e-9)
    assume(abs(best - policy.floor) > 1e-6)
    assume(second is None or abs((best - second) - policy.margin) > 1e-6)
    if best < policy.floor:
        assert result.outcome == "below_floor"
    elif second is not None and (abs(best - second) < 1e-9 or best - second < policy.margin):
        assert result.outcome == "close_second"
    elif home is not None and scored[0][1] not in home:
        assert result.outcome == "away"
    else:
        assert (result.outcome, result.person_id) == ("matched", scored[0][1])


@settings(max_examples=100, deadline=None)
@given(scenes(), st.data())
def test_property_the_order_of_people_and_decides_do_not_change_the_result(
        scene: tuple[Voiceprint, tuple[PersonPrints, ...], frozenset[int] | None, MatchPolicy],
        data: st.DataObject) -> None:
    voiceprint, prints, home, policy = scene
    shuffled = data.draw(st.permutations(prints))
    flipped = replace(policy, decides=not policy.decides)
    base = match(voiceprint, prints, home, policy)
    assert match(voiceprint, tuple(shuffled), home, flipped) == base


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=2, max_value=4), st.integers(min_value=1, max_value=3))
def test_property_a_print_of_another_length_always_raises(dim: int, extra: int) -> None:
    with pytest.raises(ValueError):
        match(Voiceprint(unit((1,) * dim), MODEL, 2000), (PersonPrints(A, (unit((1,) * (dim + extra)),)),), None, POLICY)
