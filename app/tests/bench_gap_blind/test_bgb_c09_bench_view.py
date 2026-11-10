"""Contract 9: the bench view in the prompt holds each piece's id, kind, title, version, order, size and the start of
its body, but for an outside-kind piece only id, kind and version; and it never taints a turn."""

import asyncio

import pytest
from ashley import services
from ashley.channels.respond import respond
from ashley.inference.model import ToolCall, ToolCalls
from ashley.inference.reply import Reply
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.model import Piece
from ashley.workshop.workshop import Workshop
from bench_tools_support import FakeWorkshop
from bgb_bench_support import (BENCH, BODY_MARK, BODY_OPENING, FLAGGED, IMAGE, MODEL, NOTE, READER, TITLE_MARK,
                               piece, workshop)
from later_support import Logged
from respond_support import Fakes, wired as wired

REPLY = Reply(spoken="Done.", text="Done.")


def now_of(shop: FakeWorkshop) -> str:
    services.register(Workshop, shop)
    got = asyncio.run(BenchTools(10, 1, 4).catalogue()).now
    assert got is not None
    return got


def test_c9_the_view_names_each_household_piece_by_id_kind_title_version_order_size_and_body_start() -> None:
    now = now_of(workshop(NOTE, MODEL))
    for p in (NOTE, MODEL):
        for field in (str(p.id), p.kind, p.text.title, str(p.version), str(p.place.order), p.place.size):
            assert field in now
    assert BODY_OPENING in now


@pytest.mark.parametrize("outside", [IMAGE, READER, FLAGGED])
def test_c9_an_outside_piece_shows_id_kind_and_version_only(outside: Piece) -> None:
    now = now_of(workshop(NOTE, outside))
    assert TITLE_MARK not in now and BODY_MARK not in now
    assert str(outside.id) in now and outside.kind in now and str(outside.version) in now


def test_c9_control_a_household_piece_titled_the_same_marker_is_shown() -> None:
    now = now_of(workshop(piece(3, "note", TITLE_MARK, "plain body")))
    assert TITLE_MARK in now


def test_c9_the_catalogue_reads_the_bench_once_however_often_it_is_asked() -> None:
    shop = workshop(NOTE)
    services.register(Workshop, shop)
    tools = BenchTools(10, 1, 4)
    asyncio.run(tools.catalogue())
    asyncio.run(tools.catalogue())
    assert len(shop.reads) == 1


def test_c9_bench_read_is_still_offered_for_a_re_read() -> None:
    services.register(Workshop, workshop(NOTE))
    assert "bench_read" in [s.name for s in asyncio.run(BenchTools(10, 1, 4).catalogue()).specs]


def test_c9_the_unread_gate_stays_an_edit_of_an_unread_piece_is_refused() -> None:
    shop = workshop(NOTE)
    services.register(Workshop, shop)
    tools = BenchTools(10, 1, 4)
    asyncio.run(tools.catalogue())
    edit = ToolCall("e", "bench_edit", {"piece_id": 3, "base_version": 4, "title": "t", "body": "b"})
    got = asyncio.run(tools.call(edit))
    assert got.is_error and got.content.startswith("unread:") and shop.applied == []


def test_c9_the_first_prompt_of_a_bench_turn_carries_the_view_and_no_outside_words(wired: Fakes) -> None:
    services.register(Workshop, workshop(NOTE, MODEL, IMAGE))
    wired.inference.script = [REPLY]
    asyncio.run(respond(BENCH))
    now = wired.contexts[0].tools_now
    assert now is not None and str(NOTE.id) in now and str(MODEL.id) in now and str(IMAGE.id) in now
    assert TITLE_MARK not in now and BODY_MARK not in now


def test_c9_a_turn_whose_bench_holds_notes_and_models_is_not_tainted_before_any_outside_read(
        wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    services.register(Workshop, workshop(NOTE, MODEL))
    wired.inference.script = [REPLY]
    asyncio.run(respond(BENCH))
    assert log.events("outside.tainted") == []
    (done,) = log.events("respond.done")
    assert done["tainted"] == "none"


def test_c9_an_outside_piece_on_the_bench_does_not_taint_a_turn_that_never_reads_it(
        wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    services.register(Workshop, workshop(NOTE, IMAGE, READER))
    wired.inference.script = [REPLY]
    asyncio.run(respond(BENCH))
    assert log.events("outside.tainted") == []


def test_c9_control_reading_the_outside_piece_taints_as_it_always_did(
        wired: Fakes, capsys: pytest.CaptureFixture[str]) -> None:
    log = Logged(capsys)
    services.register(Workshop, workshop(NOTE, READER))
    wired.inference.script = [ToolCalls((ToolCall("r", "bench_read_piece", {"piece_id": 8}),)), REPLY]
    asyncio.run(respond(BENCH))
    (line,) = log.events("outside.tainted")
    assert line["by"] == "bench_read_piece"
