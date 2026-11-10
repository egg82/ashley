"""`BenchPiece.reader.recording` over the real app: `PieceRecording{piece_id, starts}` for a transcript, null for a page,
for a body whose lines no longer number its starts, and for a malformed one; an edit that changes the lines drops it."""

from typing import Any

from ashley.workshop.reader import Recording, body_of
from transcript_playback_blind_support import raw_body, rig, wire_piece


def test_a_transcript_serves_its_recording_as_piece_id_and_starts(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.bench()
        pid = r.add_reader(bench, body_of("", "Talk", "[0:00] a\n[0:04] b\n[1:05] c", Recording(9, (0.0, 4.5, 65.0))))
        reader = wire_piece(r.pieces(bench), pid)["reader"]
        assert reader["recording"] == {"piece_id": 9, "starts": [0.0, 4.5, 65.0]}
        assert reader["paragraphs"] == ["[0:00] a", "[0:04] b", "[1:05] c"]
        assert reader["url"] == "" and reader["title"] == "Talk"


def test_a_page_serves_a_null_recording(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.bench()
        pid = r.add_reader(bench, body_of("https://example.com/a", "A", "one\ntwo"))
        reader: dict[str, Any] = wire_piece(r.pieces(bench), pid)["reader"]
        assert "recording" in reader and reader["recording"] is None
        assert reader["paragraphs"] == ["one", "two"]


def test_a_body_whose_lines_do_not_number_its_starts_serves_no_recording_and_the_text(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.bench()
        pid = r.add_reader(bench, body_of("", "T", "a\nb\nc", Recording(9, (0.0, 1.0))))
        reader = wire_piece(r.pieces(bench), pid)["reader"]
        assert reader["recording"] is None and reader["paragraphs"] == ["a", "b", "c"]


def test_a_malformed_recording_serves_null_and_the_piece_is_still_added(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.bench()
        pid = r.add_reader(bench, raw_body({"piece_id": "nine", "starts": [0, 1]}))
        assert wire_piece(r.pieces(bench), pid)["reader"]["recording"] is None


def test_an_edit_that_adds_a_line_drops_the_recording(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.bench()
        pid = r.add_reader(bench, body_of("", "T", "a\nb", Recording(9, (0.0, 1.0))))
        piece = wire_piece(r.pieces(bench), pid)
        assert piece["reader"]["recording"] is not None
        edited = r.command(bench, type="edit", piece_id=pid, base_version=piece["piece_version"], title="T",
                           body=body_of("", "T", "a\nb\nc", Recording(9, (0.0, 1.0))))
        assert edited.get("code") != "refused", edited
        after = wire_piece(r.pieces(bench), pid)["reader"]
        assert after["recording"] is None and after["paragraphs"] == ["a", "b", "c"]


def test_an_edit_that_keeps_the_line_count_keeps_the_recording(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.bench()
        pid = r.add_reader(bench, body_of("", "T", "a\nb", Recording(9, (0.0, 1.0))))
        piece = wire_piece(r.pieces(bench), pid)
        r.command(bench, type="edit", piece_id=pid, base_version=piece["piece_version"], title="T",
                  body=body_of("", "T", "a changed\nb", Recording(9, (0.0, 1.0))))
        after = wire_piece(r.pieces(bench), pid)["reader"]
        assert after["recording"] == {"piece_id": 9, "starts": [0.0, 1.0]}


def test_a_piece_of_another_kind_has_no_reader(db_url: str) -> None:
    with rig(db_url) as r:
        bench = r.bench()
        done = r.command(bench, type="add", kind="note", title="n", body="x", size="small")
        assert wire_piece(r.pieces(bench), int(done["piece_id"])).get("reader") is None
