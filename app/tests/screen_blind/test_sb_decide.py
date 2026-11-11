"""Contract 6 to 11 through `decide` and the screen rules, no database: the four screen kinds, one of each, the required
conversation, the limit, order and size, and the controls body."""

import json

import pytest
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Archive, Command, Edit, Move, Remove, Undo
from ashley.workshop.decide import Accepted, Decision, Refused, replay
from ashley.workshop.model import HER, By, Place, Text
from ashley.workshop.rules import Rules, load_screen
from ashley.workshop.screen_controls import decode, encode, well_formed
from sb_support import HALL, NIGHT, PORCH, wide_rules

ME = By(7)
LABELS = {"clock": "Clock", "home": "Who's home", "conversation": "Conversation", "controls": "Controls"}
SEED: list[Command] = [Add(HER, "clock", Text("Clock", ""), "small"), Add(HER, "home", Text("Who's home", ""), "small"),
                       Add(HER, "controls", Text("Controls", "[]"), "medium"),
                       Add(HER, "conversation", Text("Conversation", ""), "full")]


def decided(*commands: Command, rules: Rules | None = None, seed: bool = True) -> list[Decision]:
    """The decisions of `commands` after the seed (unless `seed` is false), the seed's own left out."""
    got = replay([*(SEED if seed else []), *commands], rules or load_screen())
    return got[len(SEED) if seed else 0:]


def reason(*commands: Command, rules: Rules | None = None, seed: bool = True) -> str:
    last = decided(*commands, rules=rules, seed=seed)[-1]
    return "accepted" if isinstance(last, Accepted) else last.reason


ENTRY = {"id": "d", "label": "A", "action": "light.turn_on", "entity_id": "light.x"}
BAD_BODIES = [
    "not json", "{}", "[1]", "", json.dumps([{k: v for k, v in ENTRY.items() if k != "entity_id"}]),
    json.dumps([{**ENTRY, "id": f"b{i}"} for i in range(13)]), json.dumps([ENTRY, ENTRY]),
    json.dumps([{**ENTRY, "action": "light.dim"}]), json.dumps([{**ENTRY, "label": "A" * 41}]),
    json.dumps([{**ENTRY, "label": "   "}]), json.dumps([{**ENTRY, "id": "Bad_Id"}]), json.dumps([{**ENTRY, "id": "d" * 41}])]


def test_k06_the_screen_rules_hold_four_screen_kinds_and_the_bench_rules_none_of_them() -> None:
    screen, bench = load_screen(), workshop_rules.load()
    assert {k: (v.family, v.label, v.max_chars, v.format, v.outside) for k, v in screen.kinds.items()} == {
        "clock": ("screen", "Clock", 1, "screen", False), "home": ("screen", "Who's home", 1, "screen", False),
        "conversation": ("screen", "Conversation", 1, "screen", False),
        "controls": ("screen", "Controls", 4000, "controls", False)}
    assert not {k for k, v in bench.kinds.items() if v.family == "screen"} and "note" in bench.kinds
    assert (screen.max_pieces, screen.title_max_chars, screen.recent_commands, screen.undo_window) == (8, 120, 12, 50)
    assert screen.required == frozenset({"conversation"}) and screen.one_each is True
    assert bench.required == frozenset() and bench.one_each is False


@pytest.mark.parametrize("kind", sorted(workshop_rules.load().kinds))
def test_k06_a_bench_kind_added_to_a_screen_is_unknown_kind(kind: str) -> None:
    assert reason(Add(ME, kind, Text("t", ""), "small")) == "unknown_kind"


@pytest.mark.parametrize("kind", ["clock", "home", "conversation", "controls"])
def test_k06_a_screen_kind_added_to_a_persons_bench_is_unknown_kind(kind: str) -> None:
    bench = workshop_rules.load()
    assert reason(Add(ME, kind, Text("t", "[]" if kind == "controls" else ""), "small"), rules=bench, seed=False) == "unknown_kind"
    assert reason(Add(ME, "note", Text("t", "b"), "small"), rules=bench, seed=False) == "accepted"


@pytest.mark.parametrize("kind", ["clock", "home", "conversation", "controls"])
def test_k07_a_kind_the_screen_already_holds_is_already_shown(kind: str) -> None:
    body = "[]" if kind == "controls" else ""
    assert reason(Add(ME, kind, Text(LABELS[kind], body), "small")) == "already_shown"


def test_k07_a_bench_may_hold_two_of_a_kind_and_a_screen_after_removing_one_may_add_it_again() -> None:
    bench = workshop_rules.load()
    two = [Add(ME, "note", Text("a", ""), "small"), Add(ME, "note", Text("b", ""), "small")]
    assert [type(d) for d in decided(*two, rules=bench, seed=False)] == [Accepted, Accepted]
    assert reason(Remove(ME, 1), Add(ME, "clock", Text("Clock", ""), "small")) == "accepted"


def test_k07_undo_of_a_remove_when_the_kind_was_added_since_is_refused_and_never_two_of_a_kind() -> None:
    got = decided(Remove(ME, 1), Add(ME, "clock", Text("Clock", ""), "small"), Undo(ME, 5))
    assert isinstance(got[-1], Refused) and got[-1].reason in ("changed_since", "already_shown")
    assert [p.kind for p in got[-1].state.pieces].count("clock") == 1


def test_k07_undo_of_a_remove_when_nothing_was_added_since_brings_the_piece_back() -> None:
    got = decided(Remove(ME, 1), Undo(ME, 5))
    assert isinstance(got[-1], Accepted)
    assert sorted(p.kind for p in got[-1].state.pieces) == sorted(LABELS)


def test_k07_a_refusal_for_a_kind_is_decided_in_the_documented_order() -> None:
    def clock(title: str, body: str) -> Add:
        return Add(ME, "clock", Text(title, body), "small")

    assert reason(Add(ME, "note", Text("", ""), "small")) == "unknown_kind"
    assert reason(clock("  ", "")) == "bad_title"
    assert reason(clock("x" * 121, "")) == "bad_title"
    assert reason(clock("Clock", "xx")) == "too_long"
    assert reason(Add(ME, "controls", Text("Controls", "not json"), "small")) == "bad_controls"
    assert reason(Add(ME, "controls", Text("Controls", "[]"), "small")) == "already_shown"
    full = wide_rules(9, 8)
    fill = [Add(HER, f"k{i}", Text(f"K{i}", ""), "small") for i in range(1, 9)]
    assert reason(*fill, Add(ME, "k1", Text("K1", ""), "small"), rules=full, seed=False) == "already_shown"
    assert reason(*fill, Add(ME, "controls", Text("Controls", "nope"), "small"), rules=full, seed=False) == "bad_controls"
    assert reason(*fill, Add(ME, "k9", Text("K9", ""), "small"), rules=full, seed=False) == "full"


def test_k08_removing_the_conversation_is_required_and_nothing_else_is() -> None:
    assert reason(Remove(ME, 4)) == "required"
    assert reason(Remove(HER, 4)) == "required"
    assert reason(Remove(ME, 99)) == "no_such_piece"
    for piece in (1, 2, 3):
        assert reason(Remove(ME, piece)) == "accepted"
    assert reason(Archive(ME, 4)) == "required"


def test_k08_an_undo_whose_inverse_would_remove_the_conversation_is_required() -> None:
    assert reason(Undo(ME, 4)) == "required"
    assert reason(Add(HER, "conversation", Text("Conversation", ""), "full"), Undo(ME, 1), seed=False) == "required"
    assert reason(Move(ME, 4, Place(0, "small")), Undo(ME, 4)) == "changed_since"
    assert reason(Undo(ME, 1)) == "accepted"


def test_k08_a_screen_with_no_conversation_to_start_with_can_still_be_given_one() -> None:
    assert reason(Add(HER, "clock", Text("Clock", ""), "small"), Add(HER, "conversation", Text("Conversation", ""), "full"),
                  seed=False) == "accepted"


def test_k09_a_ninth_piece_is_full_and_so_is_an_undo_that_would_bring_a_piece_back_past_the_limit() -> None:
    rules = wide_rules(9, 8)
    fill = [Add(HER, f"k{i}", Text(f"K{i}", ""), "small") for i in range(1, 9)]
    got = decided(*fill, Add(ME, "k9", Text("K9", ""), "small"), rules=rules, seed=False)
    assert [type(d) for d in got[:8]] == [Accepted] * 8 and isinstance(got[8], Refused) and got[8].reason == "full"
    back = decided(*fill[:8], Remove(ME, 1), Add(ME, "k9", Text("K9", ""), "small"), Undo(ME, 9), rules=rules, seed=False)
    assert isinstance(back[-1], Refused) and back[-1].reason == "full" and len(back[-1].state.pieces) == 8


def test_k10_move_reorders_and_resizes_keeping_orders_zero_to_n_minus_one() -> None:
    got = decided(Move(ME, 4, Place(0, "small")))
    assert isinstance(got[-1], Accepted)
    pieces = got[-1].state.pieces
    assert [(p.id, p.place.order, p.place.size) for p in pieces] == [(4, 0, "small"), (1, 1, "small"), (2, 2, "small"), (3, 3, "medium")]
    assert pieces[0].changed_by == 5 and pieces[1].changed_by == 1
    again = decided(Move(ME, 1, Place(3, "full")))[-1]
    assert isinstance(again, Accepted) and [p.id for p in again.state.pieces] == [2, 3, 4, 1]
    assert [p.place.order for p in again.state.pieces] == [0, 1, 2, 3] and again.state.pieces[3].place.size == "full"


def test_k10_a_move_past_the_end_is_bad_place_and_to_the_last_order_is_not() -> None:
    assert reason(Move(ME, 1, Place(4, "small"))) == "bad_place"
    assert reason(Move(ME, 1, Place(3, "small"))) == "accepted"
    assert reason(Move(ME, 99, Place(0, "small"))) == "no_such_piece"


def test_k11_an_edit_of_the_controls_with_a_body_that_is_not_the_controls_shape_is_bad_controls() -> None:
    for body in BAD_BODIES:
        assert not well_formed(body), body
        assert reason(Edit(ME, 3, 1, Text("Controls", body))) == "bad_controls", body
    assert reason(Add(ME, "controls", Text("Controls", BAD_BODIES[0]), "small"), seed=False) == "bad_controls"


def test_k11_a_well_formed_edit_is_accepted_bumps_the_version_and_a_stale_base_is_stale_base() -> None:
    body = encode((PORCH, HALL, NIGHT))
    assert well_formed(body) and decode(body) == (PORCH, HALL, NIGHT)
    got = decided(Edit(ME, 3, 1, Text("Controls", body)), Edit(ME, 3, 1, Text("Controls", "[]")))
    edited = got[0].state.piece(3)
    assert isinstance(got[0], Accepted) and edited is not None and edited.version == 2
    assert isinstance(got[1], Refused) and got[1].reason == "stale_base"
    assert reason(Edit(ME, 3, 1, Text("Controls", "[]"))) == "accepted"


def test_k11_twelve_buttons_and_a_forty_character_label_are_still_well_formed() -> None:
    twelve = [{"id": f"b{i}", "label": "L" * 40, "action": "light.turn_on", "entity_id": f"light.z{i}"} for i in range(12)]
    assert well_formed(json.dumps(twelve)) and well_formed("[]")
    assert len(decode(json.dumps(twelve))) == 12
    assert reason(Edit(ME, 3, 1, Text("Controls", json.dumps(twelve)))) == "accepted"
