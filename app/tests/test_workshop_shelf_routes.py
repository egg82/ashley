"""The shelf and reopening through the real app over a real database: archive and restore arrive as the person's
commands, a read carries the shelf beside the layout, a restore with no room is 409 `full`; closed benches are listed
and reopen, owner only; an unwired workshop is 503 on both new routes."""

from ashley.api.workshop_models import BenchDetail, BenchList, BenchSummary
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from respond_support import ALANA, SAM, Fakes, wired as wired
from test_workshop_routes import ADD, As, command, opened, unwired_as
from test_workshop_routes import signed_in as signed_in


def test_archive_and_restore_arrive_as_the_persons_commands_and_the_read_carries_the_shelf(
        signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench = opened(alana)
    command(alana, bench.id, ADD)
    command(alana, bench.id, {**ADD, "title": "tools", "size": "full"})
    assert command(alana, bench.id, {"type": "archive", "piece_id": 2}) == (200, {"seq": 3, "piece_id": 2})
    detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json())
    assert [p.id for p in detail.pieces] == [1] and detail.bench.piece_count == 1
    (shelved,) = detail.shelf
    assert (shelved.id, shelved.title, shelved.placement.size, shelved.changed_by) == (2, "tools", "full", 3)
    assert detail.recent[-1].type == "archive" and detail.undo_next == 3
    assert command(alana, bench.id, {"type": "restore", "piece_id": 2}) == (200, {"seq": 4, "piece_id": 2})
    detail = BenchDetail.model_validate(alana.get(f"/api/benches/{bench.id}").json())
    assert [(p.id, p.placement.order) for p in detail.pieces] == [(1, 0), (2, 1)] and detail.shelf == []
    status, body = command(alana, bench.id, {"type": "restore", "piece_id": 2})
    assert status == 409 and body["reason"] == "no_such_piece"


def test_closed_benches_are_listed_and_reopen_for_their_owner_alone(signed_in: As, wired: Fakes) -> None:
    alana = signed_in(ALANA)
    bench, other = opened(alana, "desk"), opened(alana, "lamp")
    alana.post(f"/api/benches/{bench.id}/close")
    closed = BenchList.model_validate(alana.get("/api/benches/closed").json()).benches
    assert [b.id for b in closed] == [bench.id] and closed[0].closed_at is not None
    sam = signed_in(SAM)
    assert BenchList.model_validate(sam.get("/api/benches/closed").json()).benches == []
    assert sam.post(f"/api/benches/{bench.id}/reopen").status_code == 404
    alana = signed_in(ALANA)
    reopened = BenchSummary.model_validate(alana.post(f"/api/benches/{bench.id}/reopen").json())
    assert reopened.closed_at is None and reopened.id == bench.id
    assert BenchList.model_validate(alana.get("/api/benches/closed").json()).benches == []
    assert [b.id for b in BenchList.model_validate(alana.get("/api/benches").json()).benches] == [other.id, bench.id]
    assert command(alana, bench.id, ADD)[0] == 200


def test_an_unwired_workshop_is_503_on_the_closed_list_and_reopen(wired: Fakes) -> None:
    alana = unwired_as(ALANA, wired)
    for response in (alana.get("/api/benches/closed"), alana.post("/api/benches/1/reopen")):
        assert response.status_code == 503 and response.json()["code"] == "unavailable"
