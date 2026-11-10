"""The shape of a measurements row, with choice rows beside number rows (design section 1): a row with no `kind` is a
number exactly as today; a choice row's required fields and limits; the sources a choice may and may not have."""

from typing import Any

import pytest
from ashley.workshop.measurements import MAX_REF, well_formed
from facts_blind_support import CHOICE_SOURCES, NUMBER, REFUSED_SOURCES, body_of, choice, cited, ok

OPTIONS = ["flat woven strap", "round cord"]


# --- a row with no kind is a number, as before ------------------------------------------------------------------------


def test_a_row_with_no_kind_is_a_number_as_before() -> None:
    assert ok(NUMBER)
    assert ok({**NUMBER, "source": "bound", "tolerance": 1})
    assert ok({**NUMBER, "source": "guessed", "asked": True, "ref": "r" * MAX_REF})


@pytest.mark.parametrize("bad", [{"unit": "cm"}, {"value": "12"}, {"source": "stated"}, {"source": "seen"}, {"extra": 1}])
def test_a_number_row_is_refused_for_the_same_reasons_as_before(bad: dict[str, Any]) -> None:
    assert not ok({**NUMBER, **bad})


def test_a_number_row_without_a_unit_is_still_refused() -> None:
    assert not ok({k: v for k, v in NUMBER.items() if k != "unit"})


@pytest.mark.parametrize("key,value", [("label", "The width"), ("options", ["a", "b"])])
def test_a_number_row_may_not_carry_choice_only_keys(key: str, value: object) -> None:
    assert not ok({**NUMBER, key: value})


def test_a_body_of_numbers_alone_and_an_empty_body_are_unchanged() -> None:
    assert well_formed("") and well_formed(body_of()) and well_formed(body_of(NUMBER))
    assert not well_formed(body_of(NUMBER, NUMBER))


# --- a choice row: required fields -----------------------------------------------------------------------------------


def test_a_guessed_choice_with_label_and_value_is_well_formed() -> None:
    assert ok(choice())


def test_a_choice_and_numbers_may_share_a_piece() -> None:
    assert ok(NUMBER, choice(), {**NUMBER, "name": "depth", "given": "lanyard_form"})


@pytest.mark.parametrize("missing", ["label", "value", "name", "source"])
def test_a_choice_row_lacking_a_required_field_is_refused(missing: str) -> None:
    assert not ok(choice(**{missing: None}))


def test_a_choice_value_must_be_text_not_a_number() -> None:
    assert not ok(choice(value=3.5))


def test_a_choice_row_may_carry_a_ref() -> None:
    assert ok(choice(ref="from the photo"))
    assert not ok(choice(ref="r" * (MAX_REF + 1)))


def test_names_are_unique_across_choice_and_number_rows() -> None:
    assert not ok(choice(name="width"), NUMBER)
    assert not ok(choice(), choice())


def test_a_number_may_say_which_choice_it_is_given() -> None:
    assert ok(choice(), {**NUMBER, "name": "strap_width", "source": "guessed", "given": "lanyard_form"})


# --- limits ----------------------------------------------------------------------------------------------------------


def test_label_of_exactly_60_is_accepted() -> None:
    assert ok(choice(label="l" * 60))


def test_label_over_60_is_refused() -> None:
    assert not ok(choice(label="l" * 61))


def test_value_of_exactly_80_is_accepted() -> None:
    assert ok(choice(value="v" * 80))


def test_value_over_80_is_refused() -> None:
    assert not ok(choice(value="v" * 81))


@pytest.mark.parametrize("count", [2, 3, 6])
def test_two_to_six_options_are_accepted(count: int) -> None:
    options = [f"option {i}" for i in range(count)]
    assert ok(choice(options=options, value=options[0]))


@pytest.mark.parametrize("count", [0, 1, 7, 12])
def test_options_outside_2_to_6_are_refused(count: int) -> None:
    options = [f"option {i}" for i in range(count)]
    assert not ok(choice(options=options, value="option 0"))


def test_value_must_be_one_of_the_options() -> None:
    assert ok(choice(options=OPTIONS, value="round cord"))
    assert not ok(choice(options=OPTIONS, value="braided"))


def test_options_are_plain_text() -> None:
    assert not ok(choice(options=["flat woven strap", 2], value="flat woven strap"))
    assert not ok(choice(options="flat woven strap, round cord"))


def test_an_option_may_be_80_characters_and_the_value_may_be_that_option() -> None:
    long = "v" * 80
    assert ok(choice(options=[long, "short"], value=long))


def test_a_row_kind_other_than_choice_or_number_is_refused() -> None:
    assert not ok(choice(kind="pick"))
    assert not ok(choice(kind=3))


# --- sources ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", CHOICE_SOURCES)
def test_each_choice_source_is_accepted_with_its_citation(source: str) -> None:
    assert ok(cited(source))


@pytest.mark.parametrize("source", REFUSED_SOURCES)
def test_number_only_sources_are_refused_on_a_choice(source: str) -> None:
    assert not ok(choice(source=source))
    assert not ok(choice(source=source, turn=41))


def test_an_unknown_source_is_refused_on_a_choice() -> None:
    assert not ok(choice(source="told"))


@pytest.mark.parametrize("bad", [True, "41", 4.5])
def test_a_turn_is_a_whole_number(bad: object) -> None:
    assert not ok(cited("stated", turn=bad))


@pytest.mark.parametrize("bad", [True, "2", 4.5])
def test_a_piece_is_a_whole_number(bad: object) -> None:
    assert not ok(cited("seen", piece=bad))
