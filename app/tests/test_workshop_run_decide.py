"""A Run on a bench from `decide`'s contract: accepted for a code piece at the version named, refused in its stated order,
changing no piece, never undone, never in the way of undoing a change around it, and kept by the codec."""

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import Add, Command, Edit, Ran, Run, Undo, type_of
from ashley.workshop.decide import Accepted, Decision, Refused, decide, replay
from ashley.workshop.model import HER, By, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.undo_walk import Step, next_undo

CODE = Kind("code", "stored", "Code", 100, "code", "text")
NOTE = Kind("note", "stored", "Note", 100)
RULES = Rules({"code": CODE, "note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
ALANA = By(7)


def run(*commands: Command) -> list[Decision]:
    return replay(commands, RULES)


def code(body: str = "print(1)") -> Add:
    return Add(ALANA, "code", Text("c", body), "small")


def test_a_run_of_a_code_piece_at_its_version_is_accepted_and_changes_no_piece() -> None:
    added, ran = run(code(), Run(ALANA, 1, 1, "python"))
    assert isinstance(ran, Accepted) and ran.seq == 2
    assert ran.effect == Ran(1, 1)
    assert ran.state.pieces == added.state.pieces


def test_run_refusals_in_their_stated_order() -> None:
    gone = run(code(), Run(ALANA, 9, 1, "python"))[-1]
    assert isinstance(gone, Refused) and gone.reason == "no_such_piece"
    note = run(Add(ALANA, "note", Text("n", "x"), "small"), Run(ALANA, 1, 1, "python"))[-1]
    assert isinstance(note, Refused) and note.reason == "not_runnable"
    stale = run(code(), Edit(ALANA, 1, 1, Text("c", "print(2)")), Run(ALANA, 1, 1, "python"))[-1]
    assert isinstance(stale, Refused) and stale.reason == "stale_base"
    added = run(code())[-1]
    without_code = Rules({"note": NOTE}, max_pieces=3, title_max_chars=5, recent_commands=10, undo_window=100)
    unknown = decide(added.state, Run(ALANA, 1, 1, "python"), without_code)
    assert isinstance(unknown, Refused) and unknown.reason == "unknown_kind"


def test_a_run_is_never_undone() -> None:
    got = run(code(), Run(ALANA, 1, 1, "python"), Undo(ALANA, 2))[-1]
    assert isinstance(got, Refused) and got.reason == "nothing_to_undo"


def test_a_run_does_not_stand_in_the_way_of_undoing_the_edit_before_it() -> None:
    got = run(code("a"), Edit(ALANA, 1, 1, Text("c", "b")), Run(HER, 1, 2, "python"), Undo(ALANA, 2))[-1]
    assert isinstance(got, Accepted)
    assert got.state.pieces[0].text.body == "a"


def test_undo_walks_past_a_run() -> None:
    assert next_undo([Step(1, True), Step(2, True, run=True)]) == 1
    assert next_undo([Step(1, True, run=True)]) is None


def test_a_run_and_its_effect_survive_the_codec() -> None:
    command = Run(ALANA, 3, 4, "python")
    assert type_of(command) == "run"
    assert decode_command(encode_command(command), ALANA) == command
    assert decode_effect(encode_effect(Ran(3, 4))) == Ran(3, 4)
