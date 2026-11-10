"""The controls body's shape, one rule at a time: the keys are exactly the four, and an entity is a non-empty string."""

import json

from ashley.workshop.screen_controls import well_formed

ENTRY = {"id": "a", "label": "A", "action": "light.turn_on", "entity_id": "light.a"}


def test_a_button_with_a_key_beyond_the_four_is_not_well_formed() -> None:
    assert well_formed(json.dumps([ENTRY]))
    assert not well_formed(json.dumps([{**ENTRY, "colour": "red"}]))


def test_a_button_with_an_empty_entity_id_is_not_well_formed() -> None:
    assert not well_formed(json.dumps([{**ENTRY, "entity_id": ""}]))
