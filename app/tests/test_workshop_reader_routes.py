"""A reader piece on the wire, through the real app over a real database: the kind is served stored with the `reader`
format; the piece reads back with its page split into paragraphs and her highlight, and the highlight is gone once the
piece changes; every other piece reads back with neither."""

import asyncio

from ashley import services
from ashley.api.workshop_models import BenchDetail, CommandRefused
from ashley.workshop import reader
from ashley.workshop.commands import Point
from ashley.workshop.model import HER, Owner
from ashley.workshop.reader import Passage
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from fastapi.testclient import TestClient
from respond_support import ALANA, wired as wired
from test_workshop_routes import As, command, opened
from test_workshop_routes import signed_in as signed_in

OWNER = Owner(ALANA.household_id, ALANA.id)
BODY = reader.body_of("https://a.example/graph", "Graph", "one\ntwo words\nthree")
READER = {"type": "add", "kind": "reader", "title": "graph", "body": BODY, "size": "large"}
NOTE = {"type": "add", "kind": "note", "title": "n", "body": "x", "size": "small"}


def read(client: TestClient, bench: int) -> BenchDetail:
    return BenchDetail.model_validate(client.get(f"/api/benches/{bench}").json())


def test_a_reader_reads_back_with_its_paragraphs_and_her_highlight(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    assert command(client, bench, READER)[0] == 200 and command(client, bench, NOTE)[0] == 200
    plain = read(client, bench)
    assert plain.pieces[0].pointer is None and plain.pieces[1].reader is None and plain.pieces[1].pointer is None
    page = plain.pieces[0].reader
    assert page is not None and (page.url, page.title, page.paragraphs) == ("https://a.example/graph", "Graph",
                                                                              ["one", "two words", "three"])
    asyncio.run(services.get(Workshop).apply(OWNER, bench, Point(HER, 1, 1, Passage(1, 4, 9))))
    pointer = read(client, bench).pieces[0].pointer
    assert pointer is not None and (pointer.seq, pointer.paragraph, pointer.start, pointer.end) == (3, 1, 4, 9)
    edit = {"type": "edit", "piece_id": 1, "base_version": 1, "title": "graph", "body": BODY.replace("three", "3")}
    assert command(client, bench, edit)[0] == 200
    assert read(client, bench).pieces[0].pointer is None


def test_a_transcript_reads_back_with_its_recording_and_the_start_of_each_line(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    body = reader.body_of("", "Transcript", "[0:00] a\n[0:07] b", reader.Recording(4, (0.0, 7.5)))
    assert command(client, bench, {**READER, "body": body})[0] == 200
    page = read(client, bench).pieces[0].reader
    assert page is not None and page.recording is not None
    assert (page.recording.piece_id, page.recording.starts) == (4, [0.0, 7.5])
    edit = {"type": "edit", "piece_id": 1, "base_version": 1, "title": "t", "body": body.replace("[0:07] b", "[0:07] b\\nc")}
    assert command(client, bench, edit)[0] == 200
    page = read(client, bench).pieces[0].reader
    assert page is not None and page.recording is None and len(page.paragraphs) == 3


def test_a_reader_body_outside_the_page_shape_is_refused_bad_reader(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    status, got = command(client, bench, {**READER, "body": "just some text"})
    assert status == 409 and CommandRefused.model_validate(got).reason == "bad_reader"


def test_an_empty_reader_has_no_page_yet(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, {**READER, "body": ""})
    assert read(client, bench).pieces[0].reader is None


def test_the_person_clears_her_highlight_and_only_at_the_version_it_was_made_against(signed_in: As) -> None:
    client = signed_in(ALANA)
    bench = opened(client).id
    command(client, bench, READER)
    command(client, bench, NOTE)
    asyncio.run(services.get(Workshop).apply(OWNER, bench, Point(HER, 1, 1, Passage(0, 0, 3))))
    stale = command(client, bench, {"type": "clear_point", "piece_id": 1, "base_version": 9})
    assert stale[0] == 409 and CommandRefused.model_validate(stale[1]).reason == "stale_base"
    note = command(client, bench, {"type": "clear_point", "piece_id": 2, "base_version": 1})
    assert note[0] == 409 and CommandRefused.model_validate(note[1]).reason == "not_reader"
    assert read(client, bench).pieces[0].pointer is not None
    assert command(client, bench, {"type": "clear_point", "piece_id": 1, "base_version": 1})[0] == 200
    assert read(client, bench).pieces[0].pointer is None
