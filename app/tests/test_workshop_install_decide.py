"""An automation piece from `decide`'s contract: its body is HA's automation config as JSON, checked on every add and
edit; she proposes installing it (a Propose, which changes no piece and is never undone), and only a person installs
it, by naming her proposal for the piece's current version; an install is undone by an Undo whose effect says what to
take back, which only a person may make; and every new command and effect survives the codec."""

import json

import pytest

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import (Add, Command, Edit, Effect, Install, Installed, Propose, Proposed, Run, Undo,
                                      Uninstalled, type_of)
from ashley.workshop.decide import Accepted, Decision, Refused, decide, replay
from ashley.workshop.model import HER, By, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.undo_walk import Step, next_undo

AUTOMATION = Kind("automation", "stored", "Automation", 5000, "automation")
NOTE = Kind("note", "stored", "Note", 100)
RULES = Rules({"automation": AUTOMATION, "note": NOTE}, max_pieces=4, title_max_chars=20, recent_commands=10, undo_window=50)
ALANA = By(7)
CONFIG = {"alias": "Porch at sunset", "description": "", "triggers": [{"trigger": "sun", "event": "sunset"}],
          "conditions": [], "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.porch"}}],
          "mode": "single"}
ID = "ashley_bench_3_piece_1"


def body(**changes: object) -> str:
    return json.dumps({**CONFIG, **changes})


def run(*commands: Command) -> list[Decision]:
    return replay(commands, RULES)


def automation(text: str | None = None) -> Add:
    return Add(ALANA, "automation", Text("porch", body() if text is None else text), "medium")


def proposed(enabled: bool = False, turn_off: str | None = None) -> list[Command]:
    return [automation(), Propose(HER, 1, 1, enabled, turn_off)]


def refused(decision: Decision) -> str:
    assert isinstance(decision, Refused), decision
    return decision.reason


@pytest.mark.parametrize("text", [
    "", body(), body(triggers=[], actions=[]), json.dumps({"alias": "a"}),
    body(mode="queued", max=3), body(description="x", variables={"a": 1})])
def test_an_automation_body_of_hass_shape_is_accepted_on_add_and_edit(text: str) -> None:
    assert isinstance(run(automation(text))[-1], Accepted)
    assert isinstance(run(automation(), Edit(ALANA, 1, 1, Text("porch", text)))[-1], Accepted)


@pytest.mark.parametrize("text", [
    "not json", "[]", '"a string"', body(triggers={"trigger": "sun"}), body(actions=["light.turn_on"]),
    body(conditions="always"), body(mode="sometimes"), body(alias=3), body(description=[]), body(id="x"),
    body(trigger=[{"trigger": "sun"}]), body(max=0), body(max=True), body(variables=[]), body(triggerz=[])])
def test_an_automation_body_outside_that_shape_is_refused_bad_automation(text: str) -> None:
    assert refused(run(automation(text))[-1]) == "bad_automation"
    assert refused(run(automation(), Edit(ALANA, 1, 1, Text("porch", text)))[-1]) == "bad_automation"


def test_any_other_kind_takes_any_body() -> None:
    assert isinstance(run(Add(ALANA, "note", Text("n", "{not json"), "small"))[-1], Accepted)


def test_a_proposal_changes_no_piece_and_carries_her_options() -> None:
    added, got = run(*proposed(True, "automation.old"))
    assert isinstance(got, Accepted)
    assert got.effect == Proposed(1, 1, True, "automation.old")
    assert got.state.pieces == added.state.pieces


def test_proposal_refusals_in_their_stated_order() -> None:
    assert refused(run(automation(), Propose(HER, 9, 1, False, None))[-1]) == "no_such_piece"
    note = Add(ALANA, "note", Text("n", "x"), "small")
    assert refused(run(note, Propose(HER, 1, 1, False, None))[-1]) == "not_installable"
    edited = Edit(ALANA, 1, 1, Text("porch", body(alias="Porch")))
    assert refused(run(automation(), edited, Propose(HER, 1, 1, False, None))[-1]) == "stale_base"
    for text in ("", body(triggers=[]), body(actions=[]), body(alias="  "), json.dumps({"triggers": CONFIG["triggers"],
                                                                                      "actions": CONFIG["actions"]})):
        assert refused(run(automation(text), Propose(HER, 1, 1, False, None))[-1]) == "incomplete"
    added = run(automation())[-1]
    without = Rules({"note": NOTE}, max_pieces=4, title_max_chars=20, recent_commands=10, undo_window=50)
    assert refused(decide(added.state, Propose(HER, 1, 1, False, None), without)) == "unknown_kind"


def test_a_person_installs_her_proposal_with_its_options() -> None:
    *_, got = run(*proposed(False, "automation.old"), Install(ALANA, 1, 2, ID))
    assert isinstance(got, Accepted) and got.seq == 3
    assert got.effect == Installed(1, 1, ID, False, "automation.old", 2)
    assert got.state.pieces[0].version == 1


def test_she_cannot_install_only_a_person_can() -> None:
    assert refused(run(*proposed(), Install(HER, 1, 2, ID))[-1]) == "needs_person"


def test_install_refusals_in_their_stated_order() -> None:
    assert refused(run(*proposed(), Install(ALANA, 9, 2, ID))[-1]) == "no_such_piece"
    assert refused(run(*proposed(), Install(ALANA, 1, 1, ID))[-1]) == "no_proposal"
    assert refused(run(*proposed(), Install(ALANA, 1, 7, ID))[-1]) == "no_proposal"
    other = [automation(), automation(), Propose(HER, 2, 1, False, None)]
    assert refused(run(*other, Install(ALANA, 1, 3, ID))[-1]) == "no_proposal"
    twice = [*proposed(), Install(ALANA, 1, 2, ID), Install(ALANA, 1, 2, ID)]
    assert refused(run(*twice)[-1]) == "no_proposal"
    edited = [*proposed(), Edit(ALANA, 1, 1, Text("porch", body(alias="Porch")))]
    assert refused(run(*edited, Install(ALANA, 1, 2, ID))[-1]) == "stale_base"
    assert refused(run(*edited, Install(HER, 1, 2, ID))[-1]) == "needs_person"
    added = run(*proposed())[-1]
    without = Rules({"note": NOTE}, max_pieces=4, title_max_chars=20, recent_commands=10, undo_window=50)
    assert refused(decide(added.state, Install(ALANA, 1, 2, ID), without)) == "unknown_kind"


def test_a_new_proposal_after_an_install_installs_again_as_an_update() -> None:
    edit = Edit(HER, 1, 1, Text("porch", body(alias="Porch light")))
    *_, got = run(*proposed(), Install(ALANA, 1, 2, ID), edit, Propose(HER, 1, 2, True, None), Install(ALANA, 1, 5, ID))
    assert isinstance(got, Accepted)
    assert got.effect == Installed(1, 2, ID, True, None, 5)


def test_a_proposal_is_never_undone_and_the_walk_passes_it() -> None:
    assert refused(run(*proposed(), Undo(ALANA, 2))[-1]) == "nothing_to_undo"
    assert next_undo([Step(1, True), Step(2, True, run=True)]) == 1


def test_a_person_undoes_an_install_naming_what_to_take_back() -> None:
    *_, got = run(*proposed(), Install(ALANA, 1, 2, ID), Undo(ALANA, 3))
    assert isinstance(got, Accepted)
    assert got.effect == Uninstalled(1, 3, ID)
    assert refused(run(*proposed(), Install(ALANA, 1, 2, ID), Undo(ALANA, 3), Undo(ALANA, 3))[-1]) == "changed_since"


def test_she_cannot_undo_an_install() -> None:
    assert refused(run(*proposed(), Install(ALANA, 1, 2, ID), Undo(HER, 3))[-1]) == "needs_person"


def test_an_edit_after_an_install_is_undone_first() -> None:
    edit = Edit(ALANA, 1, 1, Text("porch", body(alias="Porch light")))
    log = [*proposed(), Install(ALANA, 1, 2, ID), edit]
    assert refused(run(*log, Undo(ALANA, 3))[-1]) == "changed_since"
    assert isinstance(run(*log, Undo(ALANA, 4), Undo(ALANA, 3))[-1], Accepted)


def test_an_install_stands_in_the_way_of_undoing_the_edit_before_it() -> None:
    edit = Edit(ALANA, 1, 1, Text("porch", body(alias="Porch light")))
    log = [automation(), edit, Propose(HER, 1, 2, False, None), Install(ALANA, 1, 3, ID)]
    assert refused(run(*log, Undo(ALANA, 2))[-1]) == "changed_since"


def test_a_proposal_does_not_stand_in_the_way_of_undoing_the_edit_before_it() -> None:
    edit = Edit(ALANA, 1, 1, Text("porch", body(alias="Porch light")))
    got = run(automation(), edit, Propose(HER, 1, 2, False, None), Undo(ALANA, 2))[-1]
    assert isinstance(got, Accepted)


def test_a_run_of_an_automation_is_not_runnable() -> None:
    assert refused(run(automation(), Run(ALANA, 1, 1, "python"))[-1]) == "not_runnable"


@pytest.mark.parametrize("command", [Propose(HER, 3, 4, True, "automation.old"), Propose(ALANA, 3, 4, False, None),
                                     Install(ALANA, 3, 5, ID)])
def test_the_new_commands_survive_the_codec(command: Command) -> None:
    assert type_of(command) in ("propose", "install")
    assert decode_command(encode_command(command), command.by) == command


@pytest.mark.parametrize("effect", [Proposed(1, 2, True, "automation.old"), Proposed(1, 2, False, None),
                                    Installed(1, 2, ID, False, None, 4), Installed(1, 2, ID, True, "automation.x", 4),
                                    Uninstalled(1, 5, ID)])
def test_the_new_effects_survive_the_codec(effect: Effect) -> None:
    assert decode_effect(encode_effect(effect)) == effect
