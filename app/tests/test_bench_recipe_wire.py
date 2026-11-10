"""`BenchPiece.recipe`: a recipe piece served with its amounts scaled in code, the same numbers her read gives; null for
any other kind and for a body that is not a recipe."""

import dataclasses

from ashley.api.bench_recipe import recipe_of
from ashley.tools import recipe_ld
from ashley.workshop import recipe
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Piece, Place, Text
from recipe_support import MASH, PIE, page_of

KINDS = workshop_rules.load().kinds
URL = "https://recipes.example/recipes/mash"


def piece(kind: str, body: str) -> Piece:
    return Piece(1, kind, Text("Mash", body), 1, Place(0, "medium"), 1)


def mashed(serves: int | None) -> str:
    found = recipe_ld.recipe_in(page_of(MASH), URL)
    assert found is not None
    return recipe.body_of(dataclasses.replace(found, serves=serves))


def test_a_recipe_piece_is_served_scaled_for_its_headcount() -> None:
    served = recipe_of(piece("recipe", mashed(6)), KINDS["recipe"])
    assert served is not None
    assert (served.url, served.name, served.makes, served.serves, served.factor) == (
        URL, "Garlic Yukon Gold Mashed Potatoes", 4, 6, 1.5)
    assert (served.prep_min, served.cook_min, served.total_min) == (15, 25, 40)
    first, _, salt, *_ = served.ingredients
    assert (first.text, first.shown, first.amount, first.unit, first.scaled) == (
        "2 pounds Yukon gold potatoes, washed and quartered", "3 lb Yukon gold potatoes, washed and quartered", 2.0,
        "pound", True)
    assert (salt.shown, salt.amount, salt.scaled) == ("Kosher salt", None, False)
    assert served.steps[0].startswith("Place the potatoes and garlic")


def test_as_written_it_is_served_unscaled() -> None:
    served = recipe_of(piece("recipe", mashed(None)), KINDS["recipe"])
    assert served is not None and served.factor is None and served.serves is None
    assert all(line.shown == line.text and not line.scaled for line in served.ingredients)


def test_any_other_piece_or_body_has_none() -> None:
    assert recipe_of(piece("note", mashed(6)), KINDS["note"]) is None
    assert recipe_of(piece("recipe", ""), KINDS["recipe"]) is None
    assert recipe_of(piece("recipe", mashed(6)), None) is None


def test_a_metric_household_is_served_the_metric_amount_first() -> None:
    found = recipe_ld.recipe_in(page_of(PIE), URL)
    assert found is not None
    body = recipe.body_of(dataclasses.replace(found, serves=2 * (recipe.makes_of(found.yield_text) or 1)))
    both = {metric: recipe_of(piece("recipe", body), KINDS["recipe"], metric) for metric in (False, True)}
    assert both[False] is not None and both[True] is not None
    sugar = next(i for i, line in enumerate(both[False].ingredients) if "(250g)" in line.text)
    assert both[False].ingredients[sugar].shown == "2 1/2 cups (500g) granulated sugar, divided"
    assert both[True].ingredients[sugar].shown == "500g (2 1/2 cups) granulated sugar, divided"
    assert both[True].ingredients[sugar].text == both[False].ingredients[sugar].text
