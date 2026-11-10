"""`recipe_ld.recipe_in`: the schema.org Recipe a page publishes, read from invented pages' JSON-LD (a `@graph`, a list
and a lone object among them) into a `workshop.recipe.Recipe`, with the page's own address."""

import json

from ashley.tools import recipe_ld
from ashley.workshop import recipe
from recipe_support import BRITT, MASH, PIE, captured, page_of

PIE_URL = "https://recipes.example/harvest-squash-pie/"


def test_a_graph_recipe_reads_with_its_yield_times_ingredients_and_steps() -> None:
    found = recipe_ld.recipe_in(page_of(PIE), PIE_URL)
    assert found is not None
    assert found.name == "Harvest Squash Pie"
    assert found.yield_text == "8; serves 8-10; 1 cup sugared cranberries"
    assert (found.prep_min, found.cook_min, found.total_min) == (45, 65, 300)
    assert found.ingredients[0] == "1 cup (100g) fresh cranberries (not frozen)"
    assert len(found.ingredients) == 17 and len(found.steps) >= 5
    assert all(line == " ".join(line.split()) for line in (*found.ingredients, *found.steps))


def test_a_listed_recipe_reads_and_its_long_iso_durations_are_minutes() -> None:
    found = recipe_ld.recipe_in(page_of(MASH), "https://recipes.example/r")
    assert found is not None
    assert found.name == "Garlic Yukon Gold Mashed Potatoes" and found.yield_text == "4 to 6 servings"
    assert (found.prep_min, found.cook_min, found.total_min) == (15, 25, 40)
    assert found.ingredients == ("2 pounds Yukon gold potatoes, washed and quartered", "4 cloves garlic", "Kosher salt",
                                 "1 1/2 cups heavy cream, warm", "1 stick cold butter, cut into 9 pats")


def test_a_lone_recipe_object_reads_with_its_entities_and_spacing_cleaned() -> None:
    found = recipe_ld.recipe_in(page_of(BRITT), "https://recipes.example/s")
    assert found is not None
    assert found.ingredients[0] == "8 potatoes" and found.ingredients[1] == "1 clove garlic"
    assert "Heat the salad oil, add the garlic& fry until golden brown." in found.steps
    assert found.yield_text == "6 serving(s)"


def test_the_address_is_the_one_read_never_the_datas_own() -> None:
    found = recipe_ld.recipe_in(page_of(MASH), "https://read.example/page")
    assert found is not None and found.url == "https://read.example/page"


def test_a_page_without_a_recipe_node_has_none() -> None:
    blocks = captured(PIE)["blocks"]
    page = "".join(f'<script type="application/ld+json">{b}</script>' for b in blocks).replace('"Recipe"', '"Article"')
    assert recipe_ld.recipe_in(page, PIE_URL) is None
    assert recipe_ld.recipe_in("<html><body><p>2 cups flour</p></body></html>", PIE_URL) is None


def test_a_broken_block_is_skipped_and_the_next_one_read() -> None:
    page = page_of(MASH, extra='<script type="application/ld+json">{not json</script>')
    assert recipe_ld.recipe_in(page, "https://recipes.example/r") is not None


def test_only_json_ld_scripts_are_blocks() -> None:
    page = page_of(BRITT)
    assert len(recipe_ld.blocks_of(page)) == len(captured(BRITT)["blocks"]) == 1


def test_iso_durations() -> None:
    assert recipe_ld.minutes_of("PT1H5M") == 65
    assert recipe_ld.minutes_of("P0Y0M0DT0H15M0.000S") == 15
    assert recipe_ld.minutes_of("P1DT2H") == 1560
    assert recipe_ld.minutes_of("PT90S") == 2
    assert recipe_ld.minutes_of("P1M") is None and recipe_ld.minutes_of("P") is None and recipe_ld.minutes_of(15) is None


def test_steps_in_sections_flatten_in_order() -> None:
    node = {"@type": ["Recipe"], "name": "x", "recipeIngredient": ["1 egg"],
            "recipeInstructions": [{"@type": "HowToSection", "name": "A", "itemListElement": [
                {"@type": "HowToStep", "text": "one"}, {"@type": "HowToStep", "text": "two"}]}, "three<br>four"]}
    page = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    found = recipe_ld.recipe_in(page, PIE_URL)
    assert found is not None and found.steps == ("one", "two", "three", "four")


def test_what_it_reads_is_a_body_the_workshop_accepts() -> None:
    for name in (PIE, MASH, BRITT):
        found = recipe_ld.recipe_in(page_of(name), PIE_URL)
        assert found is not None and recipe.well_formed(recipe.body_of(found))
