"""Her `bench_read_piece` windows, blind: from the tool spec and the Workshop decision, through a real Postgres Workshop
with a 20-character window."""

import json

from ashley import services
from ashley.inference.model import ToolCall
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.model import Piece, Place, Text
from ashley.workshop.workshop import Workshop
from bench_replace_support import PLAIN, WINDOW, Session, scenario, windows
from bench_tools_support import FakeWorkshop
from contract.conversations_support import run


def test_windows_tile_a_body_with_multibyte_characters(db_url: str) -> None:
    body = "aé✓😀b" * 14

    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", body)
        ws = await windows(s, pid)
        assert "".join(w["body"] for w in ws) == body
        assert all(len(w["body"]) <= WINDOW for w in ws)
        assert [len(w["body"]) for w in ws] == [WINDOW, WINDOW, WINDOW, len(body) - 3 * WINDOW]
        assert [w["offset"] for w in ws] == [0, WINDOW, 2 * WINDOW, 3 * WINDOW]
        assert [w["body_cut"] for w in ws] == [True, True, True, False]

    scenario(db_url, check)


def test_a_window_starts_where_offset_says(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        for offset in (1, 7, 19, 30):
            r = await s.call("bench_read_piece", piece_id=pid, offset=offset)
            assert r.data["body"] == PLAIN[offset:offset + WINDOW] and r.data["offset"] == offset
            assert r.data["body_cut"] is (offset + WINDOW < len(PLAIN))

    scenario(db_url, check)


def test_a_body_exactly_one_window_long_is_not_cut(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN[:WINDOW])
        r = await s.call("bench_read_piece", piece_id=pid)
        assert r.data["body"] == PLAIN[:WINDOW] and r.data["body_cut"] is False
        pid2 = await s.person_adds("doc", PLAIN[:WINDOW + 1])
        r2 = await s.call("bench_read_piece", piece_id=pid2)
        assert r2.data["body"] == PLAIN[:WINDOW] and r2.data["body_cut"] is True

    scenario(db_url, check)


def test_an_offset_at_or_past_the_end_is_an_empty_uncut_window_and_a_negative_one_is_refused(db_url: str) -> None:
    async def check(s: Session) -> None:
        pid = await s.person_adds("doc", PLAIN)
        for offset in (len(PLAIN), len(PLAIN) + 500):
            r = await s.call("bench_read_piece", piece_id=pid, offset=offset)
            assert not r.is_error and r.data["body"] == "" and r.data["body_cut"] is False
        r = await s.call("bench_read_piece", piece_id=pid, offset=-1)
        assert r.is_error and r.raw.startswith("bad_arguments:")

    scenario(db_url, check)


def test_the_window_is_piece_chars_from_the_shipped_config() -> None:
    body = "x" * 12000 + "NEEDLE" + "y" * 5
    piece = Piece(1, "document", Text("T", body), 1, Place(0, "small"), 1)
    fake = FakeWorkshop(pieces=(piece,))
    services.register(Workshop, fake)
    tools = BenchTools(1, 2, 3)

    async def go() -> None:
        r = await tools.call(ToolCall("a", "bench_read_piece", {"piece_id": 1}))
        data = json.loads(r.content)
        assert data["body"] == "x" * 12000 and data["body_cut"] is True and data["offset"] == 0
        tail = json.loads((await tools.call(ToolCall("b", "bench_read_piece", {"piece_id": 1, "offset": 12000}))).content)
        assert tail["body"] == "NEEDLE" + "y" * 5 and tail["body_cut"] is False

    run(go())
