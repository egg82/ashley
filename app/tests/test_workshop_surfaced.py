"""A Surfaced from `decide`'s contract and the rows still to show (`surfacing.unshown`): a choice row is shown once for
its name and value, again only when either changes, and a guessed number only when a check rests on it, by its value and
unit; a piece a tainted turn wrote is never shown; a Surfaced changes no
piece, is never undone, never stands in the way of undoing the change before it, and is kept by the codec."""

import json

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import Add, Command, Edit, Shown, ShownRow, Surfaced, Undo, type_of
from ashley.workshop.measurements import Row, shown_value
from ashley.workshop.decide import Accepted, Decision, Refused, replay
from ashley.workshop.model import HER, By, Piece, Text
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.surfacing import Seen, unshown

MEASUREMENTS = Kind("measurements", "stored", "Measurements", 4000, "measurements")
NOTE = Kind("note", "stored", "Note", 100)
PAGE = Kind("page", "stored", "Page", 4000, "measurements", outside=True)
RULES = Rules({"measurements": MEASUREMENTS, "note": NOTE, "page": PAGE}, max_pieces=5, title_max_chars=20,
              recent_commands=10, undo_window=100)
ALANA = By(7)


def body(*rows: dict[str, object]) -> str:
    return json.dumps({"items": list(rows)})


def choice(name: str, value: str, source: str = "guessed", options: tuple[str, ...] = ("flat strap", "round cord")
           ) -> dict[str, object]:
    return {"kind": "choice", "name": name, "label": "The lanyard", "value": value, "options": list(options),
            "source": source}


def oven(value: str, name: str = "oven") -> dict[str, object]:
    return choice(name, value, "stated", ("gas", "electric"))


NUMBER: dict[str, object] = {"name": "width", "value": 12, "unit": "mm", "source": "guessed"}


def run(*commands: Command) -> list[Decision]:
    """The decisions, every Add and Edit among them accepted (a refused setup would make the test vacuous)."""
    got = replay(commands, RULES)
    assert all(isinstance(d, Accepted) for c, d in zip(commands, got) if isinstance(c, (Add, Edit))), got
    return got


def pieces_after(decisions: list[Decision]) -> tuple[Piece, ...]:
    return decisions[-1].state.pieces


def seen_by(decisions: list[Decision]) -> Seen:
    """What the log's accepted Surfaced commands name, read as `BenchView.surfaced` reads it."""
    return frozenset((d.effect.piece_id, r) for d in decisions
                     if isinstance(d, Accepted) and isinstance(d.effect, Shown) for r in d.effect.rows)


def names(rows: tuple[tuple[int, Row], ...]) -> list[tuple[int, str, str]]:
    return [(p, r.name, shown_value(r)) for p, r in rows]


def test_every_choice_row_is_unshown_until_a_surfaced_names_it_whatever_its_source() -> None:
    add = Add(HER, "measurements", Text("m", body(choice("form", "flat strap"), NUMBER,
                                                  choice("oven", "gas", "stated", ("gas", "electric")))), "small")
    added = run(add)
    assert names(unshown(pieces_after(added), frozenset(), RULES)) == [(1, "form", "flat strap"), (1, "oven", "gas")]
    shown = run(add, Surfaced(HER, 1, (ShownRow("form", "flat strap"), ShownRow("oven", "gas"))))
    assert isinstance(shown[1], Accepted) and shown[1].effect == Shown(1, (ShownRow("form", "flat strap"),
                                                                           ShownRow("oven", "gas")))
    assert unshown(pieces_after(shown), seen_by(shown), RULES) == ()


def test_a_guessed_number_is_unshown_only_when_a_check_rests_on_it_and_is_shown_once_by_value_and_unit() -> None:
    measured: dict[str, object] = {"name": "hole", "value": 6, "unit": "mm", "source": "measured"}
    add = Add(HER, "measurements", Text("m", body(NUMBER, measured, choice("form", "flat strap"))), "small")
    added = run(add)
    pieces = pieces_after(added)
    assert names(unshown(pieces, frozenset(), RULES)) == [(1, "form", "flat strap")]
    assert names(unshown(pieces, frozenset(), RULES, frozenset({"width", "hole"}))) == [(1, "width", "12 mm"), (1, "form", "flat strap")]
    told = run(add, Surfaced(HER, 1, (ShownRow("width", "12 mm"),)))
    assert isinstance(told[1], Accepted)
    assert names(unshown(pieces_after(told), seen_by(told), RULES, frozenset({"width"}))) == [(1, "form", "flat strap")]
    changed = run(add, Surfaced(HER, 1, (ShownRow("width", "12 mm"),)),
                  Edit(HER, 1, 1, Text("m", body({**NUMBER, "value": 13}, measured, choice("form", "flat strap")))))
    assert names(unshown(pieces_after(changed), seen_by(changed), RULES, frozenset({"width"}))) == [
        (1, "width", "13 mm"), (1, "form", "flat strap")]


def test_a_guessed_number_is_taken_from_the_first_piece_that_holds_its_name_and_never_from_an_outside_one() -> None:
    other: dict[str, object] = {**NUMBER, "value": 99}
    got = run(Add(HER, "page", Text("p", body(other)), "small"),
              Add(HER, "measurements", Text("m", body(NUMBER)), "small"),
              Add(HER, "measurements", Text("n", body(other)), "small"))
    assert unshown(pieces_after(got), frozenset(), RULES, frozenset({"width"})) == ()
    household = run(Add(HER, "measurements", Text("m", body(NUMBER)), "small"),
                    Add(HER, "measurements", Text("n", body(other)), "small"))
    assert names(unshown(pieces_after(household), frozenset(), RULES, frozenset({"width"}))) == [(1, "width", "12 mm")]


def test_a_row_is_shown_again_only_when_its_value_or_name_changes() -> None:
    first = Add(HER, "measurements", Text("m", body(choice("form", "flat strap"), oven("gas"))), "small")
    told = Surfaced(HER, 1, (ShownRow("form", "flat strap"), ShownRow("oven", "gas")))
    retitled = Edit(HER, 1, 1, Text("measures", body(choice("form", "flat strap"), oven("gas"))))
    revalued = Edit(HER, 1, 2, Text("measures", body(choice("form", "round cord"), oven("gas", "stove"))))
    after_title = run(first, told, retitled)
    assert unshown(pieces_after(after_title), seen_by(after_title), RULES) == ()
    after_value = run(first, told, retitled, revalued)
    assert names(unshown(pieces_after(after_value), seen_by(after_value), RULES)) == [(1, "form", "round cord"),
                                                                                      (1, "stove", "gas")]
    back = run(first, told, retitled, revalued,
               Edit(HER, 1, 3, Text("measures", body(choice("form", "flat strap"), oven("gas")))))
    assert unshown(pieces_after(back), seen_by(back), RULES) == ()


def test_a_piece_a_tainted_turn_wrote_or_of_an_outside_kind_is_never_shown_nor_surfaced() -> None:
    tainted = By(None, outside=True)
    got = run(Add(HER, "measurements", Text("m", body(choice("form", "flat strap"))), "small"),
              Edit(tainted, 1, 1, Text("m", body(choice("form", "round cord")))),
              Add(HER, "page", Text("p", body(choice("hob", "gas", options=("gas", "induction")))), "small"),
              Surfaced(HER, 1, (ShownRow("form", "round cord"),)),
              Surfaced(HER, 3, (ShownRow("hob", "gas"),)))
    assert unshown(pieces_after(got[:3]), frozenset(), RULES) == ()
    assert [d.reason for d in got[3:] if isinstance(d, Refused)] == ["bad_rows", "bad_rows"]


def test_a_surfaced_naming_what_the_piece_does_not_hold_now_is_refused_bad_rows() -> None:
    add = Add(HER, "measurements", Text("m", body(choice("form", "flat strap"), NUMBER)), "small")
    note = Add(HER, "note", Text("n", "x"), "small")
    for rows, piece in (((ShownRow("form", "round cord"),), 1), ((ShownRow("width", "12"),), 1), ((), 1),
                        ((ShownRow("form", "flat strap"), ShownRow("form", "flat strap")), 1),
                        ((ShownRow("form", "flat strap"),), 2)):
        got = run(add, note, Surfaced(HER, piece, rows))[-1]
        assert isinstance(got, Refused) and got.reason == "bad_rows", rows
    missing = run(add, Surfaced(HER, 9, (ShownRow("form", "flat strap"),)))[-1]
    assert isinstance(missing, Refused) and missing.reason == "no_such_piece"


def test_a_surfaced_changes_no_piece_is_never_undone_and_never_blocks_undoing_the_edit_before_it() -> None:
    add = Add(ALANA, "measurements", Text("m", body(choice("form", "flat strap"))), "small")
    edit = Edit(ALANA, 1, 1, Text("m", body(choice("form", "round cord"))))
    got = run(add, edit, Surfaced(HER, 1, (ShownRow("form", "round cord"),)), Undo(ALANA, 3), Undo(ALANA, 2))
    assert got[2].state.pieces == got[1].state.pieces
    assert isinstance(got[3], Refused) and got[3].reason == "nothing_to_undo"
    assert isinstance(got[4], Accepted) and json.loads(got[4].state.pieces[0].text.body)["items"][0]["value"] == "flat strap"


def test_the_codec_keeps_a_surfaced_and_its_effect() -> None:
    command = Surfaced(HER, 4, (ShownRow("form", "flat strap"), ShownRow("oven", "gas")))
    assert type_of(command) == "surfaced"
    assert decode_command(encode_command(command), HER) == command
    effect = Shown(4, command.rows)
    assert decode_effect(encode_effect(effect)) == effect
    assert decode_effect(encode_effect(effect)) != Shown(4, command.rows[:1])
