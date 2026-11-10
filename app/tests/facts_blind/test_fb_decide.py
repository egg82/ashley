"""`decide` on a measurements piece holding choices (design section 1): a piece citation is checked on the bench, a
person's own edit needs no citation, and `confirmed_measurement` covers a choice's value."""

import pytest
from ashley.workshop.decide import BenchState
from facts_blind_support import (ALANA, CITED_PIECE_SOURCES, KIND, NUMBER, accepted, bench_with_site, body_of, choice, cited,
                                 decide_add, decide_edit, refused_as)

SITE, FACTS = 1, 2


def with_body(*items: object) -> BenchState:
    """The bench with the facts piece (version 2, after the person's edit) holding `items`, written by the person, who needs no citation."""
    return accepted(decide_edit(bench_with_site(), FACTS, 1, body_of(*items), ALANA)).state


# --- a choice is a stored measurements body ---------------------------------------------------------------------------


def test_an_add_with_a_choice_row_is_accepted_and_keeps_the_body_exactly() -> None:
    body = body_of(choice(options=["flat woven strap", "round cord"]), NUMBER)
    state = accepted(decide_add(body)).state
    assert [(p.kind, p.text.body) for p in state.pieces] == [(KIND, body)]


def test_a_bad_choice_row_is_refused_bad_measurements_and_changes_nothing_but_the_seq() -> None:
    out = decide_add(body_of(choice(label="l" * 61)))
    assert refused_as(out) == "bad_measurements"
    assert out.state.pieces == () and out.state.next_seq == 2


def test_an_edit_to_a_bad_choice_is_refused_and_the_piece_stays() -> None:
    state = with_body(choice())
    out = decide_edit(state, FACTS, 2, body_of(choice(source="measured")), ALANA)
    assert refused_as(out) == "bad_measurements"
    assert out.state.pieces == state.pieces


# --- citations --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", CITED_PIECE_SOURCES)
def test_her_citation_of_a_piece_on_the_bench_is_accepted(source: str) -> None:
    accepted(decide_edit(bench_with_site(), FACTS, 1, body_of(cited(source, piece=SITE))))


@pytest.mark.parametrize("source", CITED_PIECE_SOURCES)
def test_her_citation_of_a_piece_not_on_the_bench_is_bad_citation(source: str) -> None:
    state = bench_with_site()
    out = decide_edit(state, FACTS, 1, body_of(cited(source, piece=999)))
    assert refused_as(out) == "bad_citation"
    assert out.state.pieces == state.pieces and out.state.next_seq == state.next_seq + 1


def test_her_add_citing_a_piece_not_on_the_bench_is_bad_citation() -> None:
    assert refused_as(decide_add(body_of(cited("seen", piece=1)))) == "bad_citation"


def test_her_add_citing_a_source_piece_that_is_there_is_accepted() -> None:
    accepted(decide_add(body_of(cited("datasheet", piece=SITE)), state=bench_with_site()))


@pytest.mark.parametrize("source", CITED_PIECE_SOURCES)
def test_her_seen_or_datasheet_row_naming_no_piece_is_refused(source: str) -> None:
    out = decide_edit(bench_with_site(), FACTS, 1, body_of(cited(source, piece=None)))
    assert refused_as(out) in ("bad_citation", "bad_measurements")


def test_a_malformed_row_is_refused_for_its_shape_before_its_citation() -> None:
    out = decide_edit(bench_with_site(), FACTS, 1, body_of(cited("seen", piece=999, label="l" * 61)))
    assert refused_as(out) == "bad_measurements"


def test_a_person_needs_no_citation() -> None:
    state = bench_with_site()
    accepted(decide_edit(state, FACTS, 1, body_of(choice(source="stated")), ALANA))
    accepted(decide_edit(state, FACTS, 1, body_of(choice(source="seen", piece=999)), ALANA))


def test_a_guessed_choice_needs_no_citation_from_her() -> None:
    accepted(decide_edit(bench_with_site(), FACTS, 1, body_of(choice())))


# --- the confirmed guard ----------------------------------------------------------------------------------------------

STATED = cited("stated", ref="Alana said so")


@pytest.mark.parametrize("source", ["stated", "accepted", "seen", "datasheet"])
def test_her_rewrite_of_a_confirmed_choice_is_refused(source: str) -> None:
    was = cited(source, ref="r")
    state = with_body(was)
    out = decide_edit(state, FACTS, 2, body_of({**was, "value": "round cord"}))
    assert refused_as(out) == "confirmed_measurement"
    assert out.state.pieces == state.pieces


def test_her_rewrite_of_a_guessed_choice_is_accepted() -> None:
    accepted(decide_edit(with_body(choice()), FACTS, 2, body_of(choice(value="round cord"))))


def test_her_edit_that_leaves_a_confirmed_choice_as_it_is_is_accepted() -> None:
    accepted(decide_edit(with_body(STATED), FACTS, 2, body_of(STATED, NUMBER)))


def test_her_rewrite_of_a_confirmed_choice_with_a_new_source_is_accepted() -> None:
    state = with_body(STATED)
    accepted(decide_edit(state, FACTS, 2, body_of(choice(value="round cord", source="guessed"))))


def test_her_removing_a_confirmed_choice_is_accepted() -> None:
    accepted(decide_edit(with_body(STATED, NUMBER), FACTS, 2, body_of(NUMBER)))


def test_a_person_may_rewrite_a_confirmed_choice() -> None:
    accepted(decide_edit(with_body(STATED), FACTS, 2, body_of({**STATED, "value": "round cord"}), ALANA))


def test_the_guard_still_covers_a_confirmed_number_beside_a_choice() -> None:
    state = with_body(choice(), NUMBER)
    out = decide_edit(state, FACTS, 2, body_of(choice(), {**NUMBER, "value": 99}))
    assert refused_as(out) == "confirmed_measurement"
