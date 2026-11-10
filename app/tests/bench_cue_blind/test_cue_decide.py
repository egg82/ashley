"""`decide` of a Cue from the contract: refusals in their order (`no_such_piece`, `unknown_kind`, `not_video`, `bad_cue`),
the seconds boundaries of a seek, play and pause taking none, and a cue changing no piece, version, `changed_by` or
the bench's title, only using up its `seq`."""

import math
from dataclasses import replace

import pytest
from ashley.workshop.commands import REASONS, Add, CueAction, Added, Cue, Cued, Edit, Move, Remove, type_of
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Refused, decide
from ashley.workshop.embed import MAX_START
from ashley.workshop.model import Place, Text
from bench_cue_blind_support import (ALANA, BOUNDS, HER, RULES, WITHOUT_VIDEO, accepted, add_note, add_site, add_video, cue,
                                     fold, last, reason)


def video_bench() -> BenchState:
    return accepted(last(add_video())).state


def test_type_of_a_cue_is_cue() -> None:
    assert type_of(cue(1, "play")) == "cue"


def test_the_cue_reasons_are_known_reasons() -> None:
    assert {"not_video", "bad_cue", "no_such_piece", "unknown_kind"} <= set(REASONS)


@pytest.mark.parametrize(("action", "seconds"), [("play", None), ("pause", None), ("seek", 12.5)])
def test_an_accepted_cue_logs_a_cued_effect_naming_what_was_asked(action: CueAction, seconds: float | None) -> None:
    got = accepted(decide(video_bench(), Cue(HER, 1, action, seconds), RULES))
    assert got.effect == Cued(1, action, seconds)
    assert got.seq == 2


@pytest.mark.parametrize("seconds", BOUNDS)
def test_a_seek_inside_zero_to_max_start_is_accepted(seconds: float) -> None:
    got = accepted(decide(video_bench(), cue(1, "seek", seconds), RULES))
    assert got.effect == Cued(1, "seek", seconds)


@pytest.mark.parametrize("seconds", [-1, -0.001, -1e-9, MAX_START + 1, MAX_START + 0.001, MAX_START + 1e-6, 1e12,
                                     math.nan, math.inf, -math.inf])
def test_a_seek_outside_zero_to_max_start_or_not_a_number_is_bad_cue(seconds: float) -> None:
    got = decide(video_bench(), cue(1, "seek", seconds), RULES)
    assert reason(got) == "bad_cue"


def test_a_seek_without_seconds_is_bad_cue() -> None:
    assert reason(decide(video_bench(), cue(1, "seek"), RULES)) == "bad_cue"


@pytest.mark.parametrize("action", ["play", "pause"])
@pytest.mark.parametrize("seconds", [0, 0.0, 1, 30.5, MAX_START, -1, math.nan])
def test_play_and_pause_take_no_seconds_even_a_zero(action: CueAction, seconds: float) -> None:
    assert reason(decide(video_bench(), Cue(HER, 1, action, seconds), RULES)) == "bad_cue"


def test_a_refused_cue_changes_nothing_but_uses_its_seq() -> None:
    before = video_bench()
    got = decide(before, cue(1, "seek"), RULES)
    assert isinstance(got, Refused) and got.seq == before.next_seq
    assert got.state == replace(before, next_seq=before.next_seq + 1)


# --- refusal order --------------------------------------------------------------------------------------------------


def test_a_missing_piece_is_no_such_piece_before_the_cue_is_judged() -> None:
    assert reason(decide(EMPTY, cue(99, "seek", math.nan), RULES)) == "no_such_piece"
    assert reason(decide(video_bench(), cue(99, "play", 5), RULES)) == "no_such_piece"


def test_a_piece_removed_is_no_such_piece() -> None:
    got = last(add_video(), Remove(HER, 1), cue(1, "play"))
    assert reason(got) == "no_such_piece"


def test_a_piece_whose_kind_the_rules_lost_is_unknown_kind_before_not_video_and_bad_cue() -> None:
    state = video_bench()
    assert reason(decide(state, cue(1, "play"), WITHOUT_VIDEO)) == "unknown_kind"
    assert reason(decide(state, cue(1, "seek", -5), WITHOUT_VIDEO)) == "unknown_kind"


def test_a_note_is_not_video_before_bad_cue() -> None:
    state = accepted(last(add_note())).state
    assert reason(decide(state, cue(1, "play"), RULES)) == "not_video"
    assert reason(decide(state, cue(1, "seek", -5), RULES)) == "not_video"
    assert reason(decide(state, cue(1, "play", 3), RULES)) == "not_video"


def test_a_site_piece_is_not_video_though_it_is_live() -> None:
    state = accepted(last(add_site())).state
    assert reason(decide(state, cue(1, "pause"), RULES)) == "not_video"


def test_the_kind_is_judged_on_the_piece_asked_not_on_its_neighbours() -> None:
    state = accepted(fold([add_note(), add_video(), add_site()])[-1]).state
    assert reason(decide(state, cue(1, "play"), RULES)) == "not_video"
    assert isinstance(decide(state, cue(2, "play"), RULES), Accepted)
    assert reason(decide(state, cue(3, "play"), RULES)) == "not_video"


def test_an_empty_video_draft_can_still_be_cued() -> None:
    state = accepted(last(Add(HER, "video", Text("v", ""), "medium"))).state
    assert isinstance(decide(state, cue(1, "play"), RULES), Accepted)


# --- a cue changes no piece -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", [cue(1, "play"), cue(1, "pause"), cue(1, "seek", 0), cue(1, "seek", MAX_START)])
def test_a_cue_changes_no_piece_version_or_changed_by(command: Cue) -> None:
    before = video_bench()
    after = accepted(decide(before, command, RULES)).state
    assert after.pieces == before.pieces
    assert after.shelf == before.shelf
    assert after.title == before.title
    assert after.undos == before.undos
    assert after.next_seq == before.next_seq + 1


def test_a_cue_by_her_leaves_a_persons_last_change_the_persons() -> None:
    state = accepted(fold([add_video(ALANA), Edit(ALANA, 1, 1, Text("w", '{"url": "https://youtu.be/dQw4w9WgXcQ"}')),
                          cue(1, "play"), cue(1, "seek", 4), cue(1, "pause")])[-1]).state
    piece = state.piece(1)
    assert piece is not None
    assert (piece.version, piece.changed_by) == (2, 2)


def test_a_cue_is_recorded_among_the_bench_effects_by_its_seq() -> None:
    state = accepted(fold([add_video(), cue(1, "seek", 9)])[-1]).state
    assert isinstance(state.effects[1], Added)
    assert state.effects[2] == Cued(1, "seek", 9)


def test_later_commands_on_the_piece_are_not_blocked_by_cues() -> None:
    log = fold([add_video(), cue(1, "play"), Move(HER, 1, Place(0, "full")),
                Edit(HER, 1, 1, Text("v2", '{"url": "https://youtu.be/dQw4w9WgXcQ"}'))])
    assert all(isinstance(d, Accepted) for d in log)
    piece = log[-1].state.piece(1)
    assert piece is not None and piece.version == 2 and piece.text.title == "v2"
