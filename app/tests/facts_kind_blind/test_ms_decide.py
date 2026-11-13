"""`decide` on a facts piece: an Add or Edit whose body is not empty and not well formed is refused
`bad_facts`, after `too_long`; every other kind is untouched; the refusal changes nothing but `next_seq`."""

from typing import Any

import pytest
from ashley.workshop.commands import Add, Undo
from ashley.workshop.decide import EMPTY, Refused, decide
from ashley.workshop.facts import well_formed
from ashley.workshop.model import Text
from hypothesis import given, settings
from hypothesis import strategies as st
from facts_kind_blind_support import (ALANA, GOOD, KIND, MAX_CHARS, RULES, accepted, body_of, decide_add, decide_edit,
                                        good_bodies, item_lists, refused_as, with_)

BAD = "not facts"
DISTINCT_BAD = ['{"items": [{"name": "a"}]}', body_of([with_(unit="cm")]), body_of([GOOD, GOOD]), "[]", "{}"]


def one_piece(body: str = "") -> Any:
    return accepted(decide_add(body)).state


def test_the_kind_is_a_stored_facts_format_in_the_shipped_rules() -> None:
    kind = RULES.kinds[KIND]
    assert (kind.family, kind.format) == ("stored", "facts")


# --- Add ----------------------------------------------------------------------------------------------------------


def test_an_add_with_a_well_formed_body_is_accepted_and_keeps_the_body_exactly() -> None:
    body = '{ "items":[ {"name":"w","value":1.50,"unit":"mm","source":"guessed"} ] }'
    state = accepted(decide_add(body)).state
    assert [(p.kind, p.text.body) for p in state.pieces] == [(KIND, body)]


@pytest.mark.parametrize("body", ["", body_of([])])
def test_an_add_with_an_empty_body_or_an_empty_list_is_accepted(body: str) -> None:
    accepted(decide_add(body))


@pytest.mark.parametrize("body", [BAD, *DISTINCT_BAD])
def test_an_add_with_a_bad_body_is_refused_bad_facts_and_the_bench_is_unchanged_but_for_the_seq(body: str) -> None:
    out = decide_add(body)
    assert refused_as(out) == "bad_facts"
    assert isinstance(out, Refused)
    assert out.seq == EMPTY.next_seq
    assert out.state.pieces == EMPTY.pieces and out.state.next_seq == EMPTY.next_seq + 1


def test_a_refusal_leaves_the_pieces_already_on_the_bench_alone() -> None:
    state = one_piece(body_of([GOOD]))
    out = decide(state, Add(ALANA, KIND, Text("u", BAD), "small"), RULES)
    assert refused_as(out) == "bad_facts"
    assert out.state.pieces == state.pieces


def test_the_same_bad_body_is_fine_in_every_other_kind() -> None:
    for kind in ("note", "document", "code"):
        accepted(decide(EMPTY, Add(ALANA, kind, Text("t", BAD), "small"), RULES))


def test_an_empty_title_is_refused_before_the_body_is_judged() -> None:
    assert refused_as(decide_add(BAD, title="")) == "bad_title"


def test_a_body_over_the_kinds_limit_is_too_long_not_bad_facts() -> None:
    assert refused_as(decide_add("x" * (MAX_CHARS + 1))) == "too_long"
    assert refused_as(decide_add(BAD + " " * MAX_CHARS)) == "too_long"


def test_a_body_that_is_bad_and_within_the_limit_is_bad_facts_at_the_limit_itself() -> None:
    assert refused_as(decide_add("x" * MAX_CHARS)) == "bad_facts"


def test_a_well_formed_body_of_exactly_the_limit_is_accepted_and_one_more_character_is_too_long() -> None:
    count = 400
    items = [with_(name=f"n{i}", ref="r") for i in range(count)]
    short = len(body_of(items))
    extra = MAX_CHARS - short
    assert 0 < extra <= count * 199
    for item in items:
        item["ref"] += "r" * min(199, extra - 0)
        extra -= min(199, extra)
    body = body_of(items)
    assert len(body) == MAX_CHARS and well_formed(body)
    accepted(decide_add(body))
    items[0]["ref"] += "r"
    over = body_of(items)
    assert len(over) == MAX_CHARS + 1
    assert refused_as(decide_add(over)) == "too_long"


# --- Edit ---------------------------------------------------------------------------------------------------------


def test_an_edit_to_a_well_formed_body_is_accepted_and_bumps_the_version() -> None:
    state = one_piece(body_of([GOOD]))
    new = body_of([GOOD, with_(name="depth", value=3)])
    out = accepted(decide_edit(state, 1, 1, new))
    assert (out.state.pieces[0].text.body, out.state.pieces[0].version) == (new, 2)


def test_an_edit_to_an_empty_body_is_accepted() -> None:
    accepted(decide_edit(one_piece(body_of([GOOD])), 1, 1, ""))


@pytest.mark.parametrize("body", [BAD, *DISTINCT_BAD])
def test_an_edit_to_a_bad_body_is_refused_and_the_piece_stays_as_it_was(body: str) -> None:
    state = one_piece(body_of([GOOD]))
    out = decide_edit(state, 1, 1, body)
    assert refused_as(out) == "bad_facts"
    assert out.state.pieces == state.pieces and out.state.next_seq == state.next_seq + 1


def test_an_edit_may_repair_a_piece_whose_stored_body_is_not_well_formed_only_with_a_good_one() -> None:
    state = one_piece("")
    state = accepted(decide_edit(state, 1, 1, body_of([GOOD]))).state
    assert refused_as(decide_edit(state, 1, 2, BAD)) == "bad_facts"


def test_edit_refusals_come_in_their_order_around_bad_facts() -> None:
    state = one_piece(body_of([GOOD]))
    assert refused_as(decide_edit(state, 1, 9, BAD)) == "stale_base"
    assert refused_as(decide_edit(state, 1, 1, BAD, title="")) == "bad_title"
    assert refused_as(decide_edit(state, 1, 1, "x" * (MAX_CHARS + 1))) == "too_long"
    assert refused_as(decide_edit(state, 7, 1, BAD)) == "no_such_piece"


def test_undoing_an_accepted_edit_brings_back_the_earlier_body() -> None:
    first = body_of([GOOD])
    state = one_piece(first)
    state = accepted(decide_edit(state, 1, 1, body_of([with_(value=2)]))).state
    back = accepted(decide(state, Undo(ALANA, 2), RULES)).state
    assert back.pieces[0].text.body == first


# --- the properties -----------------------------------------------------------------------------------------------


@settings(max_examples=40)
@given(body=st.one_of(good_bodies, st.text(max_size=40), st.sampled_from([BAD, "", "{}", "[]"])))
def test_add_accepts_exactly_the_empty_and_well_formed_bodies(body: str) -> None:
    out = decide_add(body)
    if body == "" or well_formed(body):
        accepted(out)
    else:
        assert refused_as(out) == "bad_facts"


@settings(max_examples=40)
@given(first=good_bodies, second=st.one_of(good_bodies, st.text(max_size=40)))
def test_edit_agrees_with_add_about_the_same_body(first: str, second: str) -> None:
    state = one_piece(first)
    added = decide_add(second)
    edited = decide_edit(state, 1, 1, second)
    assert type(added) is type(edited)
    if isinstance(added, Refused):
        assert refused_as(edited) == added.reason == "bad_facts"


@settings(max_examples=40)
@given(items=item_lists(min_size=1))
def test_a_body_with_a_name_repeated_is_refused_by_decide(items: list[dict[str, Any]]) -> None:
    assert refused_as(decide_add(body_of([*items, items[0]]))) == "bad_facts"
