"""The shelf and closed benches from `openapi.json`: archive and restore as commands (409 `full` / `no_such_piece`),
`BenchDetail.shelf`, `GET /api/benches/closed` and `POST /api/benches/{id}/reopen`, who may call them, and what Live
is told."""

import json
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

import pytest
from ashley import services
from ashley.api.models import ErrorResponse
from ashley.api.workshop_models import BenchDetail, BenchList, BenchSummary, CommandRefused, WorkshopKinds
from ashley.live.events import BenchChanged
from ashley.workshop.workshop import Workshop
from contract.conversations_support import scalar
from respond_support import Fakes, wired as wired
from shelf_route_support import Rig, build

OPENAPI = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def new_bench(rig: Rig, title: str = "bench") -> int:
    got = rig.post("/api/benches", {"title": title})
    assert got.status == 200
    return int(BenchSummary.model_validate(got.json).id)


def command(rig: Rig, bench_id: int, body: Mapping[str, object]) -> tuple[int, dict[str, Any]]:
    got = rig.post(f"/api/benches/{bench_id}/commands", body)
    return got.status, got.json


def add_body(title: str = "a", text: str = "", size: str = "small") -> dict[str, object]:
    return {"type": "add", "kind": "note", "title": title, "body": text, "size": size}


def detail(rig: Rig, bench_id: int) -> BenchDetail:
    got = rig.get(f"/api/benches/{bench_id}")
    assert got.status == 200
    return BenchDetail.model_validate(got.json)


def archive_body(piece_id: int) -> dict[str, object]:
    return {"type": "archive", "piece_id": piece_id}


def restore_body(piece_id: int) -> dict[str, object]:
    return {"type": "restore", "piece_id": piece_id}


def bench_with(rig: Rig, n: int = 3) -> int:
    b = new_bench(rig)
    for i in range(n):
        assert command(rig, b, add_body(f"p{i}", f"body{i}", ["small", "medium", "large", "full"][i % 4]))[0] == 200
    return b


def closed_ids(rig: Rig) -> list[int]:
    got = rig.get("/api/benches/closed")
    assert got.status == 200
    return [b.id for b in BenchList.model_validate(got.json).benches]


# --- archive and restore as commands -------------------------------------------------------------------------------------


def test_archive_then_restore_through_the_commands_route(rig: Rig) -> None:
    b = bench_with(rig)
    assert command(rig, b, archive_body(2)) == (200, {"seq": 4, "piece_id": 2})
    got = detail(rig, b)
    assert [p.id for p in got.pieces] == [1, 3] and [p.placement.order for p in got.pieces] == [0, 1]
    assert [(p.id, p.title, p.body, p.piece_version, p.placement.size) for p in got.shelf] == [
        (2, "p1", "body1", 1, "medium")]
    assert got.shelf[0].changed_by == 4 and got.shelf[0].changed_author == "person"
    assert command(rig, b, restore_body(2)) == (200, {"seq": 5, "piece_id": 2})
    got = detail(rig, b)
    assert [(p.id, p.placement.order, p.placement.size) for p in got.pieces] == [
        (1, 0, "small"), (3, 1, "large"), (2, 2, "medium")] and got.shelf == []
    assert [(r.seq, r.type, r.outcome, r.piece_id) for r in got.recent][-2:] == [
        (4, "archive", "accepted", 2), (5, "restore", "accepted", 2)]


def test_the_shelf_is_most_recently_archived_first_and_empty_by_default(rig: Rig) -> None:
    b = bench_with(rig)
    assert detail(rig, b).shelf == []
    for pid in (1, 3, 2):
        command(rig, b, archive_body(pid))
    got = detail(rig, b)
    assert [p.id for p in got.shelf] == [2, 3, 1] and got.pieces == []


def test_piece_count_leaves_the_shelf_out_in_every_summary(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(1))
    assert detail(rig, b).bench.piece_count == 2
    listed = BenchList.model_validate(rig.get("/api/benches").json).benches
    assert [x.piece_count for x in listed] == [2]
    rig.post(f"/api/benches/{b}/close")
    assert detail(rig, b).bench.piece_count == 2
    got = BenchList.model_validate(rig.get("/api/benches/closed").json).benches
    assert [x.piece_count for x in got] == [2]


@pytest.mark.parametrize(("body", "why"), [(archive_body(9), "no_such_piece"), (restore_body(9), "no_such_piece"),
                                           (restore_body(1), "no_such_piece"), (archive_body(0), "no_such_piece")])
def test_a_refused_archive_or_restore_is_409_with_its_reason_logged_as_the_next_seq(
        rig: Rig, body: dict[str, object], why: str) -> None:
    b = bench_with(rig)
    before = detail(rig, b)
    status, raw = command(rig, b, body)
    refused = CommandRefused.model_validate(raw)
    assert status == 409 and (refused.code, refused.reason, refused.seq) == ("refused", why, 4)
    after = detail(rig, b)
    assert (after.pieces, after.shelf) == (before.pieces, before.shelf)
    assert (after.recent[-1].seq, after.recent[-1].outcome, after.recent[-1].piece_id) == (4, why, None)


def test_archiving_a_shelved_piece_is_no_such_piece(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(2))
    status, raw = command(rig, b, archive_body(2))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "no_such_piece"


def test_a_shelved_piece_takes_no_edit_move_or_remove_over_http(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(2))
    for body in ({"type": "edit", "piece_id": 2, "base_version": 1, "title": "z", "body": ""},
                 {"type": "move", "piece_id": 2, "placement": {"order": 0, "size": "small"}},
                 {"type": "remove", "piece_id": 2}):
        status, raw = command(rig, b, body)
        assert status == 409 and CommandRefused.model_validate(raw).reason == "no_such_piece"
    assert [p.id for p in detail(rig, b).shelf] == [2]


def test_restore_onto_a_full_bench_is_409_full_at_the_shipped_limit(rig: Rig) -> None:
    limit = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json).max_pieces
    b = new_bench(rig)
    for _ in range(limit):
        assert command(rig, b, add_body())[0] == 200
    assert command(rig, b, archive_body(1))[0] == 200
    assert command(rig, b, add_body())[0] == 200
    status, raw = command(rig, b, restore_body(1))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "full"
    assert [p.id for p in detail(rig, b).shelf] == [1]


def test_an_archive_frees_a_slot_at_the_shipped_limit(rig: Rig) -> None:
    limit = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json).max_pieces
    b = new_bench(rig)
    for _ in range(limit):
        command(rig, b, add_body())
    assert command(rig, b, add_body())[0] == 409
    assert command(rig, b, archive_body(1))[0] == 200
    assert command(rig, b, add_body())[0] == 200


def test_undo_of_an_archive_and_of_a_restore_over_http(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(2))
    assert command(rig, b, {"type": "undo", "seq": 4}) == (200, {"seq": 5, "piece_id": 2})
    got = detail(rig, b)
    assert [(p.id, p.placement.order) for p in got.pieces] == [(1, 0), (2, 1), (3, 2)] and got.shelf == []
    command(rig, b, archive_body(1))
    command(rig, b, restore_body(1))
    assert command(rig, b, {"type": "undo", "seq": 7}) == (200, {"seq": 8, "piece_id": 1})
    got = detail(rig, b)
    assert [p.id for p in got.shelf] == [1] and [p.id for p in got.pieces] == [2, 3]


def test_undo_next_names_the_archive_then_the_one_before(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(2))
    assert detail(rig, b).undo_next == 4
    command(rig, b, {"type": "undo", "seq": 4})
    assert detail(rig, b).undo_next == 3


def test_undo_of_an_archive_over_http_is_full_with_no_room_and_changed_since_after_a_restore(rig: Rig) -> None:
    limit = WorkshopKinds.model_validate(rig.get("/api/workshop/kinds").json).max_pieces
    b = new_bench(rig)
    for _ in range(limit):
        command(rig, b, add_body())
    command(rig, b, archive_body(1))
    command(rig, b, add_body())
    status, raw = command(rig, b, {"type": "undo", "seq": limit + 1})
    assert status == 409 and CommandRefused.model_validate(raw).reason == "full"
    c = bench_with(rig)
    command(rig, c, archive_body(1))
    command(rig, c, restore_body(1))
    status, raw = command(rig, c, {"type": "undo", "seq": 4})
    assert status == 409 and CommandRefused.model_validate(raw).reason == "changed_since"


@pytest.mark.parametrize("body", [{"type": "archive"}, {"type": "archive", "piece_id": "x"},
                                  {"type": "archive", "piece_id": 1, "x": 1}, {"type": "restore"},
                                  {"type": "restore", "piece_id": None}, {"type": "restore", "piece_id": 1, "by": 2}])
def test_a_malformed_archive_or_restore_is_422_and_logs_nothing(rig: Rig, body: object) -> None:
    b = bench_with(rig)
    assert rig.post(f"/api/benches/{b}/commands", body).status == 422
    assert [r.seq for r in detail(rig, b).recent] == [1, 2, 3]


def test_an_accepted_archive_or_restore_is_announced_and_a_refusal_is_not(rig: Rig) -> None:
    b = bench_with(rig, 1)
    sent = len([e for e in rig.live.published if isinstance(e, BenchChanged)])
    command(rig, b, archive_body(1))
    command(rig, b, archive_body(1))
    command(rig, b, restore_body(1))
    got = [e for e in rig.live.published if isinstance(e, BenchChanged)][sent:]
    assert [(e.bench_id, e.seq) for e in got] == [(b, 2), (b, 4)]


def test_another_persons_bench_is_not_found_for_archive_and_restore(rig: Rig) -> None:
    b = bench_with(rig)
    before = detail(rig, b)
    for who in ("sam", "zed"):
        rig.as_(who)
        for body in (archive_body(1), restore_body(1)):
            got = rig.post(f"/api/benches/{b}/commands", body)
            assert got.status == 404 and ErrorResponse.model_validate(got.json).code == "not_found"
    rig.as_("alana")
    assert detail(rig, b) == before


def test_a_closed_bench_takes_no_archive_or_restore_410(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(1))
    rig.post(f"/api/benches/{b}/close")
    for body in (archive_body(2), restore_body(1)):
        status, raw = command(rig, b, body)
        assert status == 410 and ErrorResponse.model_validate(raw).code == "closed"
    assert [p.id for p in detail(rig, b).shelf] == [1]


# --- closed benches and reopen ---------------------------------------------------------------------------------------------


def test_the_closed_list_is_empty_until_something_is_closed(rig: Rig) -> None:
    new_bench(rig)
    assert closed_ids(rig) == []


def test_the_closed_list_is_the_persons_closed_benches_most_recently_closed_first(rig: Rig) -> None:
    one, two, three = new_bench(rig, "1"), new_bench(rig, "2"), new_bench(rig, "3")
    rig.post(f"/api/benches/{two}/close")
    rig.post(f"/api/benches/{one}/close")
    assert closed_ids(rig) == [one, two]
    listed = BenchList.model_validate(rig.get("/api/benches/closed").json).benches
    assert all(b.closed_at is not None for b in listed)
    assert [b.id for b in BenchList.model_validate(rig.get("/api/benches").json).benches] == [three]


def test_a_closed_bench_of_someone_else_is_not_in_my_closed_list(rig: Rig) -> None:
    mine = new_bench(rig)
    rig.post(f"/api/benches/{mine}/close")
    rig.as_("sam")
    theirs = new_bench(rig)
    rig.post(f"/api/benches/{theirs}/close")
    assert closed_ids(rig) == [theirs]
    rig.as_("zed")
    assert closed_ids(rig) == []
    rig.as_("alana")
    assert closed_ids(rig) == [mine]


def test_closed_is_a_route_of_its_own_not_a_bench_id(rig: Rig) -> None:
    assert rig.get("/api/benches/closed").status == 200
    assert BenchList.model_validate(rig.get("/api/benches/closed").json).benches == []


def test_reopen_returns_the_open_bench_and_it_leaves_the_closed_list(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(2))
    before = detail(rig, b)
    closed = BenchSummary.model_validate(rig.post(f"/api/benches/{b}/close").json)
    got = rig.post(f"/api/benches/{b}/reopen")
    assert got.status == 200
    summary = BenchSummary.model_validate(got.json)
    assert summary.closed_at is None
    assert (summary.id, summary.title, summary.opened_at, summary.piece_count, summary.thread) == (
        closed.id, closed.title, closed.opened_at, 2, closed.thread)
    assert closed_ids(rig) == []
    assert [x.id for x in BenchList.model_validate(rig.get("/api/benches").json).benches] == [b]
    after = detail(rig, b)
    assert (after.pieces, after.shelf, after.recent) == (before.pieces, before.shelf, before.recent)
    assert after.bench == summary


def test_reopen_is_idempotent_on_an_open_bench(rig: Rig) -> None:
    b = bench_with(rig)
    before = detail(rig, b).bench
    first, second = rig.post(f"/api/benches/{b}/reopen"), rig.post(f"/api/benches/{b}/reopen")
    assert (first.status, second.status) == (200, 200)
    assert BenchSummary.model_validate(first.json) == before == BenchSummary.model_validate(second.json)


def test_a_reopened_bench_takes_commands_again(rig: Rig) -> None:
    b = bench_with(rig)
    command(rig, b, archive_body(1))
    rig.post(f"/api/benches/{b}/close")
    assert command(rig, b, restore_body(1))[0] == 410
    rig.post(f"/api/benches/{b}/reopen")
    assert command(rig, b, restore_body(1)) == (200, {"seq": 5, "piece_id": 1})


def test_reopen_of_a_bench_that_is_not_the_persons_is_404_and_changes_nothing(rig: Rig) -> None:
    b = new_bench(rig)
    rig.post(f"/api/benches/{b}/close")
    for who in ("sam", "zed"):
        rig.as_(who)
        for target in (b, b + 99):
            got = rig.post(f"/api/benches/{target}/reopen")
            assert got.status == 404 and ErrorResponse.model_validate(got.json).code == "not_found"
    rig.as_("alana")
    assert closed_ids(rig) == [b]


@pytest.mark.parametrize("path", ["/api/benches/x/reopen", "/api/benches/1.5/reopen"])
def test_a_reopen_bench_id_that_is_not_a_number_is_422(rig: Rig, path: str) -> None:
    assert rig.post(path).status == 422


NEW_ROUTES = [("GET", "/api/benches/closed", None), ("POST", "/api/benches/1/reopen", None)]


@pytest.mark.parametrize(("method", "path", "body"), NEW_ROUTES)
def test_signed_out_is_401_on_the_new_routes(db_url: str, wired: Fakes, method: str, path: str, body: object) -> None:
    with build(db_url, wired, signed_in=False).client as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 401 and ErrorResponse.model_validate(response.json()).code == "unauthorized"


def test_a_reopen_from_another_site_is_403_and_changes_nothing(db_url: str, wired: Fakes) -> None:
    made = build(db_url, wired)
    with made.client as client:
        b = new_bench(made)
        made.post(f"/api/benches/{b}/close")
        app: Any = client.app
        app.dependency_overrides.clear()
        response = client.post(f"/api/benches/{b}/reopen", headers={"origin": "https://evil.test"})
        assert response.status_code == 403 and ErrorResponse.model_validate(response.json()).code == "forbidden"
    assert scalar(db_url, "SELECT closed_at IS NOT NULL FROM benches WHERE id = %s", (b,)) is True


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/benches/closed"), ("POST", "/api/benches/1/reopen")])
def test_an_unreachable_workshop_is_503_unavailable_on_the_new_routes(rig: Rig, method: str, path: str) -> None:
    services.register(Workshop, Workshop.null())
    got = rig.client.request(method, path)
    assert got.status_code == 503 and ErrorResponse.model_validate(got.json()).code == "unavailable"


# --- the published contract -------------------------------------------------------------------------------------------------


def test_openapi_declares_the_new_routes_and_the_shelf_field() -> None:
    paths = OPENAPI["paths"]
    assert "get" in paths["/api/benches/closed"] and "post" in paths["/api/benches/{bench_id}/reopen"]
    detail_schema = OPENAPI["components"]["schemas"]["BenchDetail"]
    assert "shelf" in detail_schema["properties"] and "shelf" in detail_schema["required"]
    text = json.dumps(OPENAPI["components"]["schemas"])
    assert "ArchivePieceRequest" in text and "RestorePieceRequest" in text
