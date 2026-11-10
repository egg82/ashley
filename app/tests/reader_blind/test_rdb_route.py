"""The reader piece through the routes of the real app: `BenchPiece.reader` and `BenchPiece.pointer` in a bench's
detail, the commands route refusing a bad reader body, and `clear_point` as the person's Point with no passage."""

import json
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

import pytest
from ashley.api.workshop_models import BenchDetail, BenchSummary, CommandRefused
from ashley.db.pool import PoolDatabase
from ashley.live.events import BenchChanged
from ashley.workshop import rules as workshop_rules
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.commands import Point
from ashley.workshop.model import HER
from ashley.workshop.reader import Passage
from contract.conversations_support import run
from reader_blind_support import LINES, TITLE, URL, Rig, add_note, body, build, point
from respond_support import Fakes, wired as wired

OPENAPI = json.loads((Path(__file__).resolve().parents[2] / "openapi.json").read_text())
P = Passage(0, 4, 9)


@pytest.fixture
def rig(db_url: str, wired: Fakes) -> Generator[Rig]:
    made = build(db_url, wired)
    with made.client:
        yield made


def new_bench(rig: Rig) -> int:
    got = rig.post("/api/benches", {"title": "bench"})
    assert got.status == 200
    return int(BenchSummary.model_validate(got.json).id)


def command(rig: Rig, bench: int, payload: Mapping[str, object]) -> tuple[int, dict[str, Any]]:
    got = rig.post(f"/api/benches/{bench}/commands", payload)
    return got.status, got.json


def add_body(kind: str, title: str, text: str, size: str = "medium") -> dict[str, object]:
    return {"type": "add", "kind": kind, "title": title, "body": text, "size": size}


def detail(rig: Rig, bench: int) -> BenchDetail:
    got = rig.get(f"/api/benches/{bench}")
    assert got.status == 200
    return BenchDetail.model_validate(got.json)


def her_point(rig: Rig, bench: int, piece: int, version: int, passage: Passage | None) -> int:
    """Her point on the bench, applied through a Workshop of its own on the same database (the app's stays wired)."""
    seqs: list[int] = []

    async def go() -> None:
        db = PoolDatabase(rig.w.url)
        await db.open()
        try:
            done = await PostgresWorkshop(db, workshop_rules.load()).apply(rig.w.alana, bench, point(piece, version, passage, by=HER))
            assert done.outcome == "accepted"
            seqs.append(done.seq)
        finally:
            await db.close()

    run(go())
    return seqs[0]


def reader_bench(rig: Rig) -> tuple[int, int]:
    b = new_bench(rig)
    status, got = command(rig, b, add_body("reader", "r", body()))
    assert status == 200, got
    return b, int(got["piece_id"])


def test_the_openapi_names_clear_point_reader_and_pointer() -> None:
    schemas = OPENAPI["components"]["schemas"]
    assert {"PieceReader", "PiecePointer", "ClearHighlightRequest"} <= set(schemas)
    assert set(schemas["PieceReader"]["properties"]) == {"url", "title", "paragraphs", "recording"}
    assert set(schemas["PiecePointer"]["properties"]) == {"seq", "paragraph", "start", "end"}
    assert set(schemas["ClearHighlightRequest"]["properties"]) == {"type", "piece_id", "base_version"}


def test_a_reader_piece_is_served_with_its_page_understood_and_no_pointer(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    [piece] = detail(rig, b).pieces
    assert piece.id == pid and piece.kind == "reader" and piece.pointer is None
    assert piece.reader is not None
    assert (piece.reader.url, piece.reader.title, piece.reader.paragraphs) == (URL, TITLE, list(LINES))


def test_other_kinds_and_an_empty_reader_have_no_reader_or_pointer(rig: Rig) -> None:
    b = new_bench(rig)
    assert command(rig, b, add_body("note", "n", "words"))[0] == 200
    assert command(rig, b, add_body("reader", "draft", ""))[0] == 200
    note, draft = detail(rig, b).pieces
    assert (note.reader, note.pointer, draft.reader, draft.pointer) == (None, None, None, None)


def test_a_reader_with_a_body_that_is_not_a_page_is_409_bad_reader_and_adds_nothing(rig: Rig) -> None:
    b = new_bench(rig)
    status, raw = command(rig, b, add_body("reader", "r", "just words"))
    assert status == 409
    refused = CommandRefused.model_validate(raw)
    assert (refused.code, refused.reason, refused.seq) == ("refused", "bad_reader", 1)
    assert detail(rig, b).pieces == []


def test_an_edit_to_a_bad_reader_body_is_409_bad_reader(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    status, raw = command(rig, b, {"type": "edit", "piece_id": pid, "base_version": 1, "title": "r", "body": "plain"})
    assert status == 409 and CommandRefused.model_validate(raw).reason == "bad_reader"


def test_the_paragraphs_follow_an_edit_of_the_page(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    status, _ = command(rig, b, {"type": "edit", "piece_id": pid, "base_version": 1, "title": "r", "body": body("one\ntwo")})
    assert status == 200
    [piece] = detail(rig, b).pieces
    assert piece.reader is not None and piece.reader.paragraphs == ["one", "two"] and piece.piece_version == 2


# --- the pointer ------------------------------------------------------------------------------------------------------


def test_her_point_is_served_as_the_pieces_pointer(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    seq = her_point(rig, b, pid, 1, P)
    [piece] = detail(rig, b).pieces
    assert piece.pointer is not None
    assert (piece.pointer.seq, piece.pointer.paragraph, piece.pointer.start, piece.pointer.end) == (seq, 0, 4, 9)


def test_the_pointer_is_null_once_the_piece_is_at_another_version(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    her_point(rig, b, pid, 1, P)
    assert command(rig, b, {"type": "edit", "piece_id": pid, "base_version": 1, "title": "r", "body": body("new\ntext")})[0] == 200
    [piece] = detail(rig, b).pieces
    assert piece.pointer is None and piece.piece_version == 2
    seq = her_point(rig, b, pid, 2, Passage(1, 0, 4))
    [again] = detail(rig, b).pieces
    assert again.pointer is not None and (again.pointer.seq, again.pointer.paragraph, again.pointer.end) == (seq, 1, 4)


def test_the_latest_point_is_served(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    her_point(rig, b, pid, 1, P)
    seq = her_point(rig, b, pid, 1, Passage(1, 0, 6))
    [piece] = detail(rig, b).pieces
    assert piece.pointer is not None and (piece.pointer.seq, piece.pointer.paragraph) == (seq, 1)


def test_the_log_names_a_point_by_type(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    seq = her_point(rig, b, pid, 1, P)
    row = [r for r in detail(rig, b).recent if r.seq == seq][0]
    assert (row.type, row.author, row.outcome, row.piece_id) == ("point", "ashley", "accepted", pid)


# --- clear_point ------------------------------------------------------------------------------------------------------


def clear_body(pid: int, version: int) -> dict[str, object]:
    return {"type": "clear_point", "piece_id": pid, "base_version": version}


def test_clear_point_takes_the_highlight_away_as_the_persons_point(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    her_point(rig, b, pid, 1, P)
    status, raw = command(rig, b, clear_body(pid, 1))
    assert status == 200 and raw["piece_id"] == pid and raw["seq"] == 3
    got = detail(rig, b)
    assert got.pieces[0].pointer is None
    row = [r for r in got.recent if r.seq == 3][0]
    assert (row.type, row.author, row.outcome, row.piece_id) == ("point", "person", "accepted", pid)
    assert row.person_id == rig.w.alana.person_id


def test_clear_point_changes_no_piece_version_or_author(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    before = detail(rig, b).pieces[0]
    command(rig, b, clear_body(pid, 1))
    after = detail(rig, b).pieces[0]
    assert (after.piece_version, after.changed_by, after.body, after.title) == (
        before.piece_version, before.changed_by, before.body, before.title)


def test_clear_point_where_nothing_is_pointed_is_accepted(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    assert command(rig, b, clear_body(pid, 1))[0] == 200


def test_clear_point_of_a_stale_version_is_409_stale_base(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    her_point(rig, b, pid, 1, P)
    command(rig, b, {"type": "edit", "piece_id": pid, "base_version": 1, "title": "r", "body": body("new text")})
    status, raw = command(rig, b, clear_body(pid, 1))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "stale_base"


def test_clear_point_of_a_note_is_409_not_reader(rig: Rig) -> None:
    b = new_bench(rig)
    command(rig, b, add_body("note", "n", "words"))
    status, raw = command(rig, b, clear_body(1, 1))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "not_reader"


def test_clear_point_of_a_piece_that_is_not_there_is_409_no_such_piece(rig: Rig) -> None:
    b = new_bench(rig)
    status, raw = command(rig, b, clear_body(9, 1))
    assert status == 409 and CommandRefused.model_validate(raw).reason == "no_such_piece"


def test_the_refused_clear_is_logged_with_its_reason(rig: Rig) -> None:
    b = new_bench(rig)
    command(rig, b, clear_body(9, 1))
    [row] = detail(rig, b).recent
    assert (row.type, row.outcome, row.piece_id) == ("point", "no_such_piece", None)


def test_clear_point_is_announced_like_any_change(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    before = len([x for x in rig.live.published if isinstance(x, BenchChanged)])
    command(rig, b, clear_body(pid, 1))
    sent = [x for x in rig.live.published if isinstance(x, BenchChanged)]
    assert len(sent) == before + 1 and (sent[-1].bench_id, sent[-1].seq) == (b, 2)


def test_a_stranger_cannot_clear_a_highlight_on_the_bench(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    her_point(rig, b, pid, 1, P)
    rig.as_("zed")
    status, _ = command(rig, b, clear_body(pid, 1))
    assert status == 404
    rig.as_("alana")
    assert detail(rig, b).pieces[0].pointer is not None


def test_a_household_mate_may_clear_the_highlight_on_a_shared_bench_or_is_refused_alike_for_any_command(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    her_point(rig, b, pid, 1, P)
    rig.as_("sam")
    clear = command(rig, b, clear_body(pid, 1))[0]
    other = command(rig, b, add_body("note", "n", "w"))[0]
    assert clear == other


def test_a_clear_with_missing_fields_or_a_wrong_type_is_a_validation_error(rig: Rig) -> None:
    b, pid = reader_bench(rig)
    assert command(rig, b, {"type": "clear_point", "piece_id": pid})[0] == 422
    assert command(rig, b, {"type": "clear_point", "base_version": 1})[0] == 422
    assert command(rig, b, {"type": "clear_point", "piece_id": pid, "base_version": 1, "passage": 1})[0] == 422
    assert command(rig, b, add_body("note", "n", "w"))[0] == 200 and add_note().kind == "note"
    assert Point(HER, 1, 1, None).passage is None


def test_a_note_whose_text_happens_to_be_a_page_body_has_no_reader(rig: Rig) -> None:
    b = new_bench(rig)
    assert command(rig, b, add_body("note", "n", body("lines\nof a page")))[0] == 200
    [piece] = detail(rig, b).pieces
    assert piece.kind == "note" and piece.reader is None and piece.pointer is None
