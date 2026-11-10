"""A wake rule piece and an automation's wake action, from `decide`'s contract: a wake piece's body is a JSON object of
the event it answers, her brief for that turn and the tools it may use, checked on every add and edit (`bad_wake`); an
automation piece may carry a wake action, `rest_command.ashley_wake` with structured data only, anywhere in its
actions, and one carrying anything else is `bad_automation`."""

import json

import pytest

from ashley.workshop import wake_action, wake_rule
from ashley.workshop.commands import Add, Edit
from ashley.workshop.decide import Accepted, Refused, replay
from ashley.workshop.model import By, Text
from ashley.workshop.rules import Kind, Rules, load

WAKE = Kind("wake", "stored", "Wake rule", 4000, "wake")
AUTOMATION = Kind("automation", "stored", "Automation", 5000, "automation")
RULES = Rules({"wake": WAKE, "automation": AUTOMATION}, max_pieces=4, title_max_chars=20, recent_commands=10,
              undo_window=50)
ALANA = By(7)
BRIEF = "Greet him if it has been a while."
RULE = {"event": "alana_arrived", "brief": BRIEF, "tools": ["HassTurnOn", "house_state"]}
WAKE_DATA: dict[str, object] = {"event": "alana_arrived", "event_id": "{{ context.id }}", "who": "person.alana",
                                 "when": "{{ now().isoformat() }}"}
WAKES = {"action": "rest_command.ashley_wake", "data": WAKE_DATA}
CONFIG = {"alias": "Alana home", "triggers": [{"trigger": "state", "entity_id": "person.alana", "to": "home"}],
          "actions": [WAKES]}


def rule(**changes: object) -> str:
    return json.dumps({**RULE, **changes})


def config(*actions: object) -> str:
    return json.dumps({**CONFIG, "actions": list(actions)})


def wake_data(**changes: object) -> dict[str, object]:
    data = {**WAKE_DATA, **changes}
    return {"action": "rest_command.ashley_wake", "data": {k: v for k, v in data.items() if v is not None}}


def outcome(kind: str, text: str) -> str:
    for made in (replay([Add(ALANA, kind, Text("t", text), "medium")], RULES)[-1],
                 replay([Add(ALANA, kind, Text("t", ""), "medium"), Edit(ALANA, 1, 1, Text("t", text))], RULES)[-1]):
        if isinstance(made, Refused):
            return made.reason
        assert isinstance(made, Accepted)
    return "accepted"


def test_the_shipped_kinds_offer_a_wake_rule() -> None:
    kind = load().kinds["wake"]
    assert kind.format == "wake" and kind.family == "stored"


@pytest.mark.parametrize("text", ["", rule(), rule(tools=[]), rule(brief="x" * wake_rule.MAX_BRIEF)])
def test_a_wake_rule_of_its_shape_is_accepted_on_add_and_edit(text: str) -> None:
    assert outcome("wake", text) == "accepted"


@pytest.mark.parametrize("text", [
    "not json", "[]", json.dumps({"event": "a", "brief": "b"}), rule(extra=1), rule(event="Alana arrived"),
    rule(event=""), rule(event="9lives"), rule(event="a" * 65), rule(brief="   "), rule(brief=3),
    rule(brief="x" * (wake_rule.MAX_BRIEF + 1)), rule(tools="HassTurnOn"), rule(tools=[3]),
    rule(tools=["two words"]), rule(tools=["a", "a"])])
def test_a_wake_rule_outside_its_shape_is_refused_bad_wake(text: str) -> None:
    assert outcome("wake", text) == "bad_wake"


def test_a_wake_rule_reads_back_as_its_fields() -> None:
    assert wake_rule.rule_of(rule()) == wake_rule.WakeRule("alana_arrived", BRIEF, ("HassTurnOn", "house_state"))
    assert wake_rule.rule_of("") is None and wake_rule.rule_of("{}") is None


def test_an_automation_may_carry_a_wake_action_anywhere_in_its_actions() -> None:
    nested = {"if": [{"condition": "state", "entity_id": "sun.sun", "state": "below_horizon"}], "then": [WAKES]}
    for text in (config(WAKES), config({"action": "light.turn_on"}, WAKES), config(nested),
                 config(wake_data(who=None, when=None)), config(wake_data(what="garage_open"))):
        assert outcome("automation", text) == "accepted", text


@pytest.mark.parametrize("action", [
    wake_data(event="Alana is home"), wake_data(event=None), wake_data(event_id=None), wake_data(who="Alana"),
    wake_data(what="the garage is open"), wake_data(when="tonight"), wake_data(note="{{ 'hi' }}"),
    wake_data(who=3), {"action": "rest_command.ashley_wake"}, {**WAKES, "data": "event=alana_arrived"},
    {**WAKES, "data_template": {}}, wake_data(who="{{ 'person.alana' }} and more")])
def test_a_wake_action_with_anything_but_structured_data_is_bad_automation(action: object) -> None:
    assert outcome("automation", config(action)) == "bad_automation"
    nested = {"choose": [{"conditions": [], "sequence": [action]}]}
    assert outcome("automation", config(nested)) == "bad_automation"


def test_the_wake_action_names_the_service_ha_is_set_up_with() -> None:
    assert wake_action.SERVICE == "rest_command.ashley_wake"
    assert wake_action.events_of(json.loads(config(WAKES, wake_data(event="garage_open")))) == (
        "alana_arrived", "garage_open")


@pytest.mark.parametrize("named", [{"service": "rest_command.ashley_wake"},
                                   {"action": "{{ 'rest_command.ashley_wake' }}"},
                                   {"service": "{{ 'rest_command.' ~ 'ashley_wake' }}"}])
def test_a_wake_call_named_any_other_way_is_bad_automation_whatever_its_data(named: dict[str, str]) -> None:
    for data in (WAKE_DATA, {**WAKE_DATA, "message": "welcome him home"}):
        action = {**named, "data": data}
        assert not wake_action.well_formed({"actions": [action]})
        assert outcome("automation", config(action)) == "bad_automation"
    assert outcome("automation", config({"service": "light.turn_on", "target": {"entity_id": "light.hall"}})) == "accepted"
