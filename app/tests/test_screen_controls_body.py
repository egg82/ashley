"""The controls body's shape, one rule at a time: the keys are exactly the four, and an entity is a non-empty string."""

import json

from ashley.channels.screen_args import buttons_of
from ashley.tools.screen_specs import specs
from ashley.workshop.rules import load_screen
from ashley.workshop.screen_controls import well_formed

ENTRY = {"id": "a", "label": "A", "action": "light.turn_on", "entity_id": "light.a"}


def test_a_button_with_a_key_beyond_the_four_is_not_well_formed() -> None:
    assert well_formed(json.dumps([ENTRY]))
    assert not well_formed(json.dumps([{**ENTRY, "colour": "red"}]))


def test_a_button_with_an_empty_entity_id_is_not_well_formed() -> None:
    assert not well_formed(json.dumps([{**ENTRY, "entity_id": ""}]))


def test_a_toggle_button_is_well_formed() -> None:
    assert well_formed(json.dumps([{**ENTRY, "action": "light.toggle"}]))


def test_she_may_ask_for_a_toggle_and_her_tool_names_it() -> None:
    rules = load_screen()
    _, controls = buttons_of({"buttons": [{"label": "Hall", "action": "light.toggle", "entity_id": "light.a"}],
                              "base_version": 1, "piece_id": 3}, {"light.a": "light"}, rules)
    assert [c.action for c in controls] == ["light.toggle"]
    buttons = next(s for s in specs(rules) if s.name == "screen_buttons")
    assert "light.toggle" in json.dumps(buttons.parameters)
