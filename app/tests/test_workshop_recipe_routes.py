"""A recipe piece on the wire, through the real app over a real database: it reads back with its recipe scaled for its
headcount (`BenchPiece.recipe`), the person's edit of its headcount rescales it, a body outside the recipe shape is
refused `bad_recipe`, and every other piece reads back with none."""

import dataclasses

from ashley.api.workshop_models import BenchDetail, CommandRefused
from ashley.tools import recipe_ld
from ashley.workshop import recipe
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from recipe_support import MASH, page_of
from respond_support import ALANA, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

URL = "https://recipes.example/recipes/mash"
FOUND = recipe_ld.recipe_in(page_of(MASH), URL)
assert FOUND is not None
BODY = recipe.body_of(dataclasses.replace(FOUND, serves=6))
RECIPE = {"type": "add", "kind": "recipe", "title": "Mash", "body": BODY, "size": "medium"}
NOTE = {"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"}


def read(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def test_a_recipe_reads_back_scaled_and_rescales_when_its_headcount_changes(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    assert command(client, bench, RECIPE)[0] == 200 and command(client, bench, NOTE)[0] == 200
    pieces = read(client, bench).pieces
    served = pieces[0].recipe
    assert pieces[1].recipe is None
    assert served is not None and (served.url, served.makes, served.serves, served.factor) == (URL, 4, 6, 1.5)
    assert served.ingredients[0].shown == "3 lb Yukon gold potatoes, washed and quartered"
    edit = {"type": "edit", "piece_id": 1, "base_version": 1, "title": "Mash",
            "body": BODY.replace('"serves": 6', '"serves": 2')}
    assert command(client, bench, edit)[0] == 200
    rescaled = read(client, bench).pieces[0].recipe
    assert rescaled is not None and rescaled.factor == 0.5
    assert rescaled.ingredients[0].shown == "1 lb Yukon gold potatoes, washed and quartered"


def test_a_recipe_body_outside_the_shape_is_refused_bad_recipe(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    status, got = command(client, bench, {**RECIPE, "body": "2 cups flour"})
    assert status == 409 and CommandRefused.model_validate(got).reason == "bad_recipe"
    assert read(client, bench).pieces == []
