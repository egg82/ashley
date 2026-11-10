"""What a device's screen allows, judged by the Workshop's one `decide` under the screen rules: kinds of its own, one of
each, the conversation always kept, a controls body that is a list of buttons, and an Undo that cannot bring back a second
of a kind or take the conversation away."""

import json
from dataclasses import replace

import pytest
from ashley.live.events import ScreenChanged, Shown, decode, encode
from ashley.workshop import rules as workshop_rules
from ashley.workshop import screen_controls, screen_seed
from ashley.workshop.commands import Add, Archive, Command, Edit, Move, Remove, Undo
from ashley.workshop.decide import Accepted, Decision, Refused, replay
from ashley.workshop.model import HER, Piece, Place, Text
from ashley.workshop.rules import Rules

SCREEN = workshop_rules.load_screen()
BENCH = workshop_rules.load()
BUTTON = {"id": "a", "label": "A", "action": "light.turn_on", "entity_id": "light.a"}
SEED = screen_seed.load(SCREEN)
KINDS = ["clock", "home", "controls", "conversation"]


def seeded() -> list[Command]:
    return list(screen_seed.commands(SEED, SCREEN, ()))


def decided(commands: list[Command], rules: Rules = SCREEN) -> Decision:
    return replay(commands, rules, screen_seed.TITLE)[-1]


def refused(commands: list[Command], rules: Rules = SCREEN) -> str:
    got = decided(commands, rules)
    assert isinstance(got, Refused), got
    return got.reason


def added(kind: str, body: str = "") -> Add:
    return Add(HER, kind, Text(kind, body), "small")


def test_the_bench_rules_leave_the_screen_kinds_out_and_the_screen_rules_keep_only_them() -> None:
    assert not {"clock", "home", "conversation", "controls"} & set(BENCH.kinds)
    assert set(SCREEN.kinds) == {"clock", "home", "conversation", "controls"}
    assert SCREEN.required == {"conversation"} and SCREEN.one_each and not BENCH.one_each and not BENCH.required
    assert all(k.family == "screen" for k in SCREEN.kinds.values())


def test_the_seed_lays_out_the_four_pieces_as_shipped() -> None:
    got = decided(seeded())
    assert isinstance(got, Accepted)
    assert [p.kind for p in got.state.pieces] == KINDS and [p.id for p in got.state.pieces] == [1, 2, 3, 4]
    assert [p.place.size for p in got.state.pieces] == ["small", "small", "medium", "full"]


def test_a_seed_the_screen_rules_refuse_or_that_is_not_a_list_of_kinds_and_sizes_is_a_value_error() -> None:
    shapes: list[object] = [[], {}, [{"kind": "clock"}], [{"kind": "note", "size": "small"}],
                            [{"kind": "clock", "size": "huge"}], [{"kind": "clock", "size": "small"}]]
    for bad in shapes:
        with pytest.raises(ValueError):
            screen_seed.seed_of(bad, SCREEN)


def test_a_bench_kind_on_a_screen_and_a_screen_kind_on_a_bench_are_unknown_kinds() -> None:
    assert refused([added("note")]) == "unknown_kind"
    assert refused([added("clock")], BENCH) == "unknown_kind"


def test_a_kind_already_on_the_screen_is_refused_and_removing_it_first_lets_it_back() -> None:
    assert refused([*seeded(), added("clock")]) == "already_shown"
    assert isinstance(decided([*seeded(), Remove(HER, 1), added("clock")]), Accepted)


def test_the_only_conversation_cannot_be_removed_archived_or_undone_away() -> None:
    assert refused([*seeded(), Remove(HER, 4)]) == "required"
    assert refused([*seeded(), Archive(HER, 4)]) == "required"
    assert refused([*seeded(), Undo(HER, 4)]) == "required"
    assert isinstance(decided([*seeded(), Undo(HER, 1)]), Accepted)


def test_an_undo_of_a_remove_is_refused_when_the_kind_came_back_in_the_meantime() -> None:
    log = [*seeded(), Remove(HER, 1), added("clock")]
    assert refused([*log, Undo(HER, 5)]) in {"already_shown", "changed_since"}
    assert sum(p.kind == "clock" for p in _pieces(decided([*log, Undo(HER, 5)]))) <= 1


def _pieces(got: Decision) -> tuple[Piece, ...]:
    return got.state.pieces


def test_a_piece_past_the_most_is_full_under_rules_with_a_smaller_most() -> None:
    small = replace(SCREEN, max_pieces=3)
    assert refused([*seeded()[:3], added("conversation")], small) == "full"
    assert isinstance(decided([*seeded()[:2], added("conversation")], small), Accepted)


def test_a_move_reorders_and_resizes_and_a_place_past_the_end_is_bad() -> None:
    moved = decided([*seeded(), Move(HER, 4, Place(0, "large"))])
    assert isinstance(moved, Accepted)
    assert [(p.kind, p.place.order, p.place.size) for p in moved.state.pieces][0] == ("conversation", 0, "large")
    assert [p.place.order for p in moved.state.pieces] == [0, 1, 2, 3]
    assert refused([*seeded(), Move(HER, 4, Place(4, "small"))]) == "bad_place"


@pytest.mark.parametrize("body", [
    "not json", "", "{}", json.dumps([BUTTON] * 2),
    json.dumps([{**BUTTON, "id": f"b{i}"} for i in range(13)]),
    json.dumps([{**BUTTON, "action": "light.explode"}]),
    json.dumps([{**BUTTON, "label": "x" * 41}]),
    json.dumps([{**BUTTON, "label": "  "}]),
    json.dumps([{**BUTTON, "id": "Bad Id"}]),
    json.dumps([{k: v for k, v in BUTTON.items() if k != "entity_id"}]),
])
def test_a_controls_body_that_is_not_a_list_of_buttons_is_bad_controls(body: str) -> None:
    assert refused([*seeded(), Edit(HER, 3, 1, Text("Controls", body))]) == "bad_controls"


def test_a_good_controls_body_is_stored_and_a_stale_base_is_refused() -> None:
    body = screen_controls.encode(screen_controls.decode(json.dumps([BUTTON])))
    ok = decided([*seeded(), Edit(HER, 3, 1, Text("Controls", body))])
    piece = ok.state.piece(3)
    assert isinstance(ok, Accepted) and piece is not None and piece.version == 2
    assert refused([*seeded(), Edit(HER, 3, 1, Text("Controls", body)), Edit(HER, 3, 1, Text("Controls", "[]"))]) == "stale_base"


def test_twelve_buttons_are_the_most_and_a_body_over_the_kinds_length_is_too_long() -> None:
    twelve = json.dumps([{**BUTTON, "id": f"b{i}"} for i in range(12)])
    assert isinstance(decided([*seeded(), Edit(HER, 3, 1, Text("Controls", twelve))]), Accepted)
    big = json.dumps([{**BUTTON, "id": f"b{i}", "entity_id": "light." + "x" * 400} for i in range(12)])
    assert refused([*seeded(), Edit(HER, 3, 1, Text("Controls", big))]) == "too_long"


def test_screen_changed_is_the_households_alone_and_travels_as_type_screen() -> None:
    event = ScreenChanged(Shown(1, None), 7, 5)
    assert json.loads(encode(event))["type"] == "screen" and decode(encode(event)) == event
    for shown in (Shown(1, 2), Shown(1, None, 7)):
        with pytest.raises(ValueError):
            ScreenChanged(shown, 7, 5)
