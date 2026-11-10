"""A reader piece over the real Workshop: put up by the number of a page that was read this turn and never by text she
wrote, her `bench_point` resolves a quote to a passage, logs it as hers, announces it as a change of the bench and
keeps it for a later read for as long as the piece is at that version, and it is no change of the piece or the bench."""

import json

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.live.events import BenchChanged
from ashley.live.live import Live
from ashley.tools.bench_tools import BenchTools
from ashley.tools.results import ReadPage, Results
from ashley.workshop import reader
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Edit
from ashley.workshop.model import HER, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.reader import Passage
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive

URL = "https://a.example/graph"
TEXT = "A graph is a set of vertices.\nEdges join two vertices.\nA tree is a graph with no cycles."


def add(**args: object) -> ToolCall:
    return ToolCall("a", "bench_add", {"kind": "reader", "title": "Graphs", **args})


def test_a_reader_is_put_up_by_a_read_page_and_pointed_at(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    live = FakeLive()
    numbered = Results()
    numbered.record(URL)
    numbered.record("https://b.example/unread")
    numbered.keep(1, ReadPage("Graph", "Graph\n" + TEXT))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, live)
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "graphs")
            hers = BenchTools(alana.household_id, alana.person_id, bench.id, results=numbered)
            for bad, start in (({"result": 2}, "unread_page:"), ({"result": 9}, "unknown_result:"),
                               ({"body": "typed"}, "bad_arguments:"), ({"result": 1, "body": "typed"}, "bad_arguments:")):
                got = await hers.call(add(**bad))
                assert got.is_error and got.content.startswith(start), (bad, got.content)
            assert (await shop.read(alana, bench.id)).pieces == ()
            made = await hers.call(add(result=1))
            assert not made.is_error
            moved = (await shop.open_benches(alana))[0].last_changed_at
            assert moved is not None
            piece = (await shop.read(alana, bench.id)).pieces[0]
            assert reader.page_of(piece.text.body) == reader.Page(URL, "Graph", TEXT)

            shown = json.loads((await hers.call(ToolCall("r", "bench_read_piece", {"piece_id": 1}))).content)
            assert shown["body"] == TEXT and shown["url"] == URL and shown["page_title"] == "Graph"

            quote = "Edges join"
            got = await hers.call(ToolCall("p", "bench_point", {"piece_id": 1, "quote": quote}))
            assert not got.is_error
            view = await shop.read(alana, bench.id)
            pointer = view.pointers[1]
            assert (pointer.seq, pointer.version, pointer.passage) == (2, 1, Passage(1, 0, 10))
            assert view.changes[1].by == HER and view.bench.last_changed_at == moved
            assert [e.seq for e in live.published if isinstance(e, BenchChanged)] == [1, 2]
            assert view.undo_next == 1

            for bad_quote in ("vertices", "nowhere", "vertices.\nEdges"):
                bad = await hers.call(ToolCall("b", "bench_point", {"piece_id": 1, "quote": bad_quote}))
                assert bad.is_error and bad.content.startswith("bad_arguments:"), bad_quote
            assert (await shop.read(alana, bench.id)).pointers[1].seq == 2

            await hers.call(ToolCall("p", "bench_point", {"piece_id": 1, "quote": "tree"}))
            assert (await shop.read(alana, bench.id)).pointers[1].passage == Passage(2, 2, 6)
            await hers.call(ToolCall("p", "bench_point", {"piece_id": 1, "quote": ""}))
            assert 1 not in (await shop.read(alana, bench.id)).pointers

            await hers.call(ToolCall("p", "bench_point", {"piece_id": 1, "quote": "tree"}))
            edited = Edit(HER, 1, 1, Text("Graphs", reader.body_of(URL, "Graph", TEXT + "\nmore")))
            assert (await shop.apply(alana, bench.id, edited)).outcome == "accepted"
            assert (await shop.read(alana, bench.id)).pointers[1].version == 1

            made_note = await hers.call(add(kind="note", body="n", title="Note"))
            note_id = json.loads(made_note.content)["piece_id"]
            note = await hers.call(ToolCall("n", "bench_point", {"piece_id": note_id, "quote": ""}))
            assert note.is_error and note.content.startswith("not_reader:")
            await hers.call(ToolCall("r", "bench_read_piece", {"piece_id": 1}))
            replace = await hers.call(ToolCall("x", "bench_replace", {"piece_id": 1, "base_version": 2, "old": "tree",
                                                                       "new": "forest"}))
            assert replace.is_error and replace.content.startswith("bad_arguments:")
        finally:
            await database.close()

    run(scenario())


def test_a_long_page_is_held_whole_up_to_the_kinds_limit_and_read_on_in_windows(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    limit = workshop_rules.load().kinds["reader"].max_chars
    lines = [f"line {i:05d} " + "x" * 40 for i in range(limit // 40)]
    full = "\n".join(lines)
    numbered = Results()
    numbered.record(URL)
    numbered.record(URL + "2")
    numbered.keep(1, ReadPage("", "\n".join(lines[:2000])))
    numbered.keep(2, ReadPage("", full))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "long")
            hers = BenchTools(alana.household_id, alana.person_id, bench.id, results=numbered)
            assert not (await hers.call(add(result=1))).is_error and not (await hers.call(add(result=2))).is_error
            first, second = (await shop.read(alana, bench.id)).pieces
            held = reader.page_of(first.text.body)
            assert held is not None and held.text == "\n".join(lines[:2000]) and len(held.text) > 12000
            assert len(second.text.body) <= limit and len(second.text.body) > limit - 200
            cut = reader.page_of(second.text.body)
            assert cut is not None and full.startswith(cut.text) and len(cut.text) < len(full)
            seen = ""
            while True:
                got = json.loads((await hers.call(ToolCall("r", "bench_read_piece", {"piece_id": first.id,
                                                                                    "offset": len(seen)}))).content)
                seen += got["body"]
                if not got["body_cut"]:
                    break
            assert seen == held.text
        finally:
            await database.close()

    run(scenario())
