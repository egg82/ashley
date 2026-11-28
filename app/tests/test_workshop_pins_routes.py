"""Pins and boxes through the real app over a real database: a person's move sets a pin and box that the read returns,
a move that leaves them out keeps them, null clears one, a pin or box out of bounds is a 409 `bad_place`, and the
request's shape is checked."""

from ashley.api.workshop_models import BenchDetail, PieceBox, PiecePin
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import ALANA, Fakes, wired as wired
from test_workshop_routes import ADD, As, command, opened
from test_workshop_routes import signed_in as signed_in


def test_a_persons_move_sets_keeps_and_clears_a_pin_and_box(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    command(alana, bench.id, ADD)
    command(alana, bench.id, ADD)

    def placement() -> tuple[PiecePin | None, PieceBox | None]:
        detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json())
        found = next(p for p in detail.pieces if p.id == 1).placement
        return found.pin, found.box

    assert placement() == (None, None)
    pinned = {"type": "move", "piece_id": 1,
              "placement": {"order": 0, "size": "small", "pin": {"x": -80, "y": 120}, "box": {"w": 400, "h": 300}}}
    assert command(alana, bench.id, pinned) == (200, {"seq": 3, "piece_id": 1})
    assert placement() == (PiecePin(x=-80, y=120), PieceBox(w=400, h=300))
    command(alana, bench.id, {"type": "move", "piece_id": 1, "placement": {"order": 1, "size": "full"}})
    assert placement() == (PiecePin(x=-80, y=120), PieceBox(w=400, h=300))
    command(alana, bench.id, {"type": "move", "piece_id": 1, "placement": {"order": 1, "size": "full", "box": None}})
    assert placement() == (PiecePin(x=-80, y=120), None)
    command(alana, bench.id, {"type": "undo", "seq": 5})
    assert placement() == (PiecePin(x=-80, y=120), PieceBox(w=400, h=300))


def test_a_pin_or_box_out_of_bounds_is_409_and_a_malformed_one_422(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    command(alana, bench.id, ADD)
    at = {"order": 0, "size": "small"}
    for extra in ({"pin": {"x": 10**9, "y": 0}}, {"box": {"w": 1, "h": 300}}, {"box": {"w": 400, "h": 10**6}}):
        status, raw = command(alana, bench.id, {"type": "move", "piece_id": 1, "placement": {**at, **extra}})
        assert (status, raw["reason"]) == (409, "bad_place")
    for extra in ({"pin": {"x": 1}}, {"box": {"w": 400, "h": 300, "d": 1}}, {"pin": {"x": "left", "y": 0}}):
        assert command(alana, bench.id, {"type": "move", "piece_id": 1, "placement": {**at, **extra}})[0] == 422
