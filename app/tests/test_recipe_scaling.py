"""Scaling a recipe is arithmetic in code: `quantity` reads the amount an ingredient line starts with and writes it back
multiplied, and `recipe.scaled` multiplies by the headcount over the page's yield count. Lines are the invented pages'
own (`recipe_captured/`)."""

import dataclasses

import pytest

from ashley.tools import recipe_ld
from ashley.workshop import quantity, recipe
from recipe_support import BRITT, MASH, PIE, page_of


def _recipe(name: str, serves: int | None) -> recipe.Recipe:
    found = recipe_ld.recipe_in(page_of(name), "https://example.org/r")
    assert found is not None
    return dataclasses.replace(found, serves=serves)


@pytest.mark.parametrize(("line", "low", "high", "unit"), [
    ("2 pounds Yukon gold potatoes, washed and quartered", 2, None, "pound"),
    ("1 1/2 cups heavy cream, warm", 1.5, None, "cup"),
    ("1 and 1/4 cups (250g) granulated sugar, divided", 1.25, None, "cup"),
    ("1/4 teaspoon celery seed", 0.25, None, "teaspoon"),
    ("8 potatoes", 8, None, None),
    ("one 15-ounce can (425g) pumpkin puree*", 1, None, None),
    ("2-3 carrots", 2, 3, None),
    ("1½ tsp salt", 1.5, None, "teaspoon"),
    ("250g flour", 250, None, "gram"),
])
def test_an_amount_is_read_with_its_unit(line: str, low: float, high: float | None, unit: str | None) -> None:
    found = quantity.amount_of(line)
    assert found is not None
    assert (found.low, found.high, None if found.unit is None else found.unit.key) == (low, high, unit)


@pytest.mark.parametrize("line", ["Kosher salt", "salt, pepper and paprika to taste", "15-ounce can tomatoes",
                                  "Homemade Pie Dough (full recipe makes 2 crusts)", "", "3 to 2 eggs"])
def test_a_line_without_an_amount_has_none(line: str) -> None:
    assert quantity.amount_of(line) is None


@pytest.mark.parametrize(("line", "factor", "shown"), [
    ("2 pounds Yukon gold potatoes, washed and quartered", 1.5, "3 lb Yukon gold potatoes, washed and quartered"),
    ("1 cup (100g) fresh cranberries (do not use frozen)", 0.75, "3/4 cup (75g) fresh cranberries (do not use frozen)"),
    ("1 1/2 cups heavy cream, warm", 2, "3 cups heavy cream, warm"),
    ("1 stick cold butter, cut into 9 pats", 1.5, "1 1/2 sticks cold butter, cut into 9 pats"),
    ("one 15-ounce can (425g) pumpkin puree*", 2, "2 15-ounce can (425g) pumpkin puree*"),
    ("2-3 carrots", 2, "4–6 carrots"),
    ("4 cloves garlic", 0.25, "1 clove garlic"),
])
def test_a_scaled_line_rewrites_only_its_amount(line: str, factor: float, shown: str) -> None:
    found = quantity.amount_of(line)
    assert found is not None
    assert quantity.scaled_line(line, found, factor) == shown


@pytest.mark.parametrize(("value", "unit", "text"), [
    (0.75, "cup", "3/4"), (2.25, "cup", "2 1/4"), (1 / 3, "cup", "1/3"), (2.0, "cup", "2"), (0.99, "cup", "1"),
    (0.5625, None, "1/2"), (1.6875, "teaspoon", "1 2/3"), (0.03, "cup", "1/8"), (1.01, None, "1"),
    (187.5, "gram", "190"), (152.4, "gram", "150"), (99.6, "gram", "100"), (56.25, "gram", "56"), (0.2, "gram", "1"),
    (187.5, "millilitre", "188"), (7.25, "kilogram", "7.2"),
])
def test_numbers_read_as_a_cook_reads_them(value: float, unit: str | None, text: str) -> None:
    assert quantity.number_text(value, None if unit is None else quantity.UNITS[unit]) == text


def test_a_recipe_is_scaled_by_headcount_over_its_yield() -> None:
    view = recipe.scaled(_recipe(MASH, 6))
    assert view.makes == 4 and view.factor == 1.5
    assert [line.shown for line in view.lines] == [
        "3 lb Yukon gold potatoes, washed and quartered", "6 cloves garlic", "Kosher salt",
        "2 1/4 cups heavy cream, warm", "1 1/2 sticks cold butter, cut into 9 pats"]
    assert [line.scaled for line in view.lines] == [True, True, False, True, True]


def test_a_yields_first_number_is_its_count() -> None:
    assert recipe.scaled(_recipe(PIE, 6)).makes == 8
    assert recipe.makes_of("serves 8-10") == 8 and recipe.makes_of("6 serving(s)") == 6
    assert recipe.makes_of("") is None and recipe.makes_of("one loaf") == 1 and recipe.makes_of("a big pot") is None


def test_without_a_headcount_or_a_count_nothing_is_scaled() -> None:
    as_written = recipe.scaled(_recipe(BRITT, None))
    assert as_written.factor is None and all(line.shown == line.text for line in as_written.lines)
    countless = recipe.scaled(dataclasses.replace(_recipe(BRITT, 4), yield_text="a big pot"))
    assert countless.factor is None and not any(line.scaled for line in countless.lines)


def test_her_read_carries_the_scaled_amounts_and_marks_the_rest() -> None:
    text = recipe.text_of(_recipe(MASH, 6))
    assert "Scaled for 6 from 4" in text and "- 3 lb Yukon gold potatoes" in text
    assert "- Kosher salt (as written)" in text and "Steps (as the page wrote them, for 4):" in text
    assert "Times: prep 15 min, cook 25 min, total 40 min" in text


def test_the_body_round_trips_and_its_shape_is_checked() -> None:
    made = _recipe(PIE, 6)
    assert recipe.recipe_of(recipe.body_of(made)) == made
    assert recipe.well_formed("")
    good = recipe.body_of(made)
    for bad in (good.replace('"serves": 6', '"serves": 0'), good.replace('"serves": 6', '"serves": "6"'),
                good.replace("https://", "http://"), good.replace('"prep_min": 45', '"prep_min": -1'),
                good.replace('"prep_min": 45', '"prep_min": true'), good.replace('"serves": 6', '"serves": 6, "x": 1'),
                "[]", "{"):
        assert not recipe.well_formed(bad), bad


@pytest.mark.parametrize(("line", "factor", "shown"), [
    ("1 cup milk", 0.5625, "1/2 cup milk"),
    ("1 cup milk", 0.6, "2/3 cup milk"),
    ("3 tsp salt", 0.5625, "1 2/3 tsp salt"),
    ("2 eggs", 0.7, "1 1/3 eggs"),
    ("1 cup milk", 0.03, "1/8 cup milk"),
    ("100 g flour", 0.5625, "56 g flour"),
    ("250 g flour", 0.5625, "140 g flour"),
    ("250 g flour", 0.6, "150 g flour"),
    ("250 g flour", 0.5, "125 g flour"),
    ("1 cup (240ml) milk", 1.0, "1 cup (240ml) milk"),
    ("1 cup (240ml) milk", 0.5625, "1/2 cup (135ml) milk"),
])
def test_scaled_amounts_are_kitchen_quantities(line: str, factor: float, shown: str) -> None:
    found = quantity.amount_of(line)
    assert found is not None
    assert quantity.scaled_line(line, found, factor) == shown


def test_the_exact_scaled_number_stays_in_the_data() -> None:
    view = recipe.scaled(dataclasses.replace(_recipe(MASH, 6), serves=9, yield_text="16"))
    assert view.factor == 0.5625
    assert [line.amount for line in view.lines][:2] == [2, 4]


def test_her_read_states_the_exact_factor() -> None:
    text = recipe.text_of(dataclasses.replace(_recipe(MASH, 9), yield_text="16"))
    assert "multiplied by 0.5625" in text
