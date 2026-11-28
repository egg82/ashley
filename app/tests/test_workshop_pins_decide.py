"""Pins and boxes through `decide` and the codec: a person's Move sets, clears or keeps each, a pin or box out of the
rules' bounds (or under a screen's rules, which have none) refused `bad_place`, an undo putting back the exact pin and
box the move replaced, and replay (through the codec, and from log rows written before pins) reproducing them."""

from hypothesis import given, settings
from hypothesis import strategies as st
import pytest

from ashley.workshop.codec import decode_command, decode_effect, encode_command, encode_effect
from ashley.workshop.commands import KEEP, Add, Archive, Command, Keep, Move, Moved, Remove, Restore, Undo
from ashley.workshop.decide import Accepted, Decision, Refused, replay
from ashley.workshop.model import HER, Box, By, Pin, Place, Text
from ashley.workshop.rules import Kind, Layout, Rules

NOTE = Kind("note", "stored", "Note", 10)
LAYOUT = Layout(pin_reach=1000, min_w=100, max_w=800, min_h=50, max_h=600)
RULES = Rules({"note": NOTE}, max_pieces=5, title_max_chars=5, recent_commands=10, undo_window=100, layout=LAYOUT)
SCREEN = Rules({"note": NOTE}, max_pieces=5, title_max_chars=5, recent_commands=10, undo_window=100)
ALANA = By(7)
PIN, BOX = Pin(-40, 120), Box(300, 200)


def add(title: str = "a") -> Add:
    return Add(ALANA, "note", Text(title, ""), "small")


def move(piece_id: int, order: int, pin: Pin | None | Keep = KEEP, box: Box | None | Keep = KEEP,
         by: By = ALANA) -> Move:
    return Move(by, piece_id, Place(order, "small"), pin, box)


def last(*commands: Command, rules: Rules = RULES) -> Decision:
    return replay(commands, rules)[-1]


def place_of(decision: Decision, piece_id: int) -> Place:
    found = next(p for p in (*decision.state.pieces, *decision.state.shelf) if p.id == piece_id)
    return found.place


def test_a_persons_move_sets_a_pin_and_a_box() -> None:
    got = last(add(), add(), move(1, 0, PIN, BOX))
    assert isinstance(got, Accepted)
    assert got.effect == Moved(1, Place(0, "small"), Place(0, "small", PIN, BOX))
    assert place_of(got, 1) == Place(0, "small", PIN, BOX) and got.state.pieces[0].changed_by == 3


def test_a_move_that_leaves_them_out_keeps_the_pieces_pin_and_box() -> None:
    got = last(add(), add(), move(1, 0, PIN, BOX), Move(HER, 1, Place(1, "large")))
    assert isinstance(got, Accepted)
    assert place_of(got, 1) == Place(1, "large", PIN, BOX)


def test_each_is_kept_or_cleared_on_its_own() -> None:
    cleared_pin = last(add(), move(1, 0, PIN, BOX), move(1, 0, None))
    cleared_box = last(add(), move(1, 0, PIN, BOX), move(1, 0, box=None))
    assert place_of(cleared_pin, 1) == Place(0, "small", None, BOX)
    assert place_of(cleared_box, 1) == Place(0, "small", PIN, None)


def test_undo_puts_back_the_exact_pin_and_box_a_move_replaced() -> None:
    other = Pin(5, 6)
    pinned = (add(), add(), move(1, 0, PIN, BOX))
    assert place_of(last(*pinned, Undo(ALANA, 3)), 1) == Place(0, "small")
    assert place_of(last(*pinned, move(1, 1, other, None), Undo(ALANA, 4)), 1) == Place(0, "small", PIN, BOX)
    assert place_of(last(*pinned, Move(HER, 1, Place(1, "full")), Undo(HER, 4)), 1) == Place(0, "small", PIN, BOX)


def test_an_undo_to_an_order_past_the_end_keeps_the_pin_and_box_it_puts_back() -> None:
    got = last(add(), add(), move(2, 1, PIN, BOX), move(2, 0, None, None), Remove(ALANA, 1), Undo(ALANA, 4))
    assert isinstance(got, Accepted) and place_of(got, 2) == Place(0, "small", PIN, BOX)


def test_a_pin_and_box_come_back_with_a_restore_and_with_the_undo_of_a_remove() -> None:
    pinned = (add(), add(), move(1, 0, PIN, BOX))
    assert place_of(last(*pinned, Archive(ALANA, 1), Restore(ALANA, 1)), 1) == Place(1, "small", PIN, BOX)
    assert place_of(last(*pinned, Remove(ALANA, 1), Undo(ALANA, 4)), 1) == Place(0, "small", PIN, BOX)


@pytest.mark.parametrize("pin, box", [
    (Pin(1001, 0), KEEP), (Pin(0, -1001), KEEP), (KEEP, Box(99, 200)), (KEEP, Box(801, 200)),
    (KEEP, Box(300, 49)), (KEEP, Box(300, 601)), (Pin(2**40, 0), Box(300, 200))])
def test_a_pin_or_box_out_of_bounds_is_refused_bad_place(pin: Pin | Keep, box: Box | Keep) -> None:
    got = last(add(), move(1, 0, pin, box))
    assert isinstance(got, Refused) and got.reason == "bad_place"


def test_the_bounds_themselves_are_held() -> None:
    edge = last(add(), move(1, 0, Pin(-1000, 1000), Box(100, 50)), move(1, 0, box=Box(800, 600)))
    assert isinstance(edge, Accepted) and place_of(edge, 1) == Place(0, "small", Pin(-1000, 1000), Box(800, 600))


def test_a_screens_rules_refuse_a_pin_or_box_and_keep_moving_pieces() -> None:
    for pin, box in ((PIN, KEEP), (KEEP, BOX)):
        got = last(add(), add(), move(1, 1, pin, box), rules=SCREEN)
        assert isinstance(got, Refused) and got.reason == "bad_place"
    moved = last(add(), add(), move(1, 1, None, None), rules=SCREEN)
    assert isinstance(moved, Accepted) and place_of(moved, 1) == Place(1, "small")


def test_a_moves_place_carries_no_pin_or_box_of_its_own() -> None:
    with pytest.raises(ValueError):
        Move(ALANA, 1, Place(0, "small", PIN))


def test_the_codec_tells_keep_from_clear_and_round_trips_a_pinned_place() -> None:
    keep, clear, both = move(1, 0), move(1, 0, None, None), move(1, 0, PIN, BOX)
    assert "pin" not in encode_command(keep) and "box" not in encode_command(keep)
    assert encode_command(clear)["pin"] is None and encode_command(clear)["box"] is None
    for command in (keep, clear, both):
        assert decode_command(encode_command(command), ALANA) == command
    effect = Moved(1, Place(0, "small"), Place(2, "full", PIN, BOX))
    assert decode_effect(encode_effect(effect)) == effect


def test_log_rows_from_before_pins_decode_and_replay_as_they_did() -> None:
    commands = [{"type": "add", "kind": "note", "title": "a", "body": "", "size": "small"},
                {"type": "add", "kind": "note", "title": "b", "body": "", "size": "medium"},
                {"type": "move", "piece_id": 1, "place": {"order": 1, "size": "large"}},
                {"type": "undo", "seq": 3}]
    decoded = [decode_command(raw, ALANA) for raw in commands]
    assert decoded[2] == Move(ALANA, 1, Place(1, "large"), KEEP, KEEP)
    final = replay(decoded, RULES)
    assert [(p.id, p.place) for p in final[-1].state.pieces] == [(1, Place(0, "small")), (2, Place(1, "medium"))]
    effect = {"type": "moved", "piece_id": 1, "before": {"order": 0, "size": "small"},
              "after": {"order": 1, "size": "large"}}
    assert decode_effect(effect) == Moved(1, Place(0, "small"), Place(1, "large"))
    assert encode_effect(decode_effect(effect)) == effect
    added = {"type": "added", "piece": {"id": 1, "kind": "note", "title": "a", "body": "", "version": 1,
                                        "place": {"order": 0, "size": "small"}, "changed_by": 1}}
    assert encode_effect(decode_effect(added)) == added


_pins = st.one_of(st.just(KEEP), st.none(), st.builds(Pin, st.integers(-1200, 1200), st.integers(-1200, 1200)))
_boxes = st.one_of(st.just(KEEP), st.none(), st.builds(Box, st.integers(80, 900), st.integers(30, 700)))
_moves = st.builds(move, st.integers(1, 3), st.integers(0, 3), _pins, _boxes)
_undos = st.builds(Undo, st.just(ALANA), st.integers(1, 20))


@settings(max_examples=150, deadline=None)
@given(st.lists(st.one_of(_moves, _undos), max_size=14))
def test_replay_through_the_codec_reproduces_every_pin_box_and_outcome(tail: list[Command]) -> None:
    commands: list[Command] = [add("a"), add("b"), add("c"), *tail]
    direct = replay(commands, RULES)
    logged = replay([decode_command(encode_command(c), c.by) for c in commands], RULES)
    assert [type(d) for d in direct] == [type(d) for d in logged]
    assert direct[-1].state.pieces == logged[-1].state.pieces
    for done in direct:
        if isinstance(done, Accepted):
            assert decode_effect(encode_effect(done.effect)) == done.effect
