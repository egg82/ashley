"""Her bench tools over the real Workshop: what she adds and edits is logged as hers, announced on Live to the owner
as a person's change is, and undoable by the person; another person's bench is not found to her; a bench she opens from
web chat is the speaker's."""

import json

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.inference.model import ToolCall
from ashley.live.events import BenchChanged
from ashley.live.live import Live
from ashley.tools.bench_tools import BenchTools
from ashley.tools.open_bench import OpenBenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Undo
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive


def test_her_note_and_edit_are_logged_as_hers_announced_and_undoable_by_the_person(db_url: str) -> None:
    home = household(db_url)
    alana, sam = Owner(home, person(db_url, home)), Owner(home, person(db_url, home))
    live = FakeLive()

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, live)
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "shed")
            hers = BenchTools(alana.household_id, alana.person_id, bench.id)
            added = await hers.call(ToolCall("a", "bench_add", {"kind": "note", "title": "Wood", "body": "pine"}))
            piece_id = json.loads(added.content)["piece_id"]
            edited = await hers.call(ToolCall("e", "bench_edit", {"piece_id": piece_id, "base_version": 1,
                                                                  "title": "Wood", "body": "oak"}))
            assert not edited.is_error, edited.content
            log = await shop.log(alana, bench.id)
            assert [(row.seq, row.by.author, row.outcome) for row in log] == [(1, "ashley", "accepted"),
                                                                             (2, "ashley", "accepted")]
            assert [e.seq for e in live.published if isinstance(e, BenchChanged)] == [1, 2]
            await shop.apply(alana, bench.id, Undo(By(alana.person_id), 2))
            (piece,) = (await shop.read(alana, bench.id)).pieces
            assert piece.text.body == "pine"
            stale = await hers.call(ToolCall("s", "bench_edit", {"piece_id": piece_id, "base_version": 2,
                                                                 "title": "Wood", "body": "ash"}))
            assert stale.is_error and stale.content.startswith("stale_base:")
            theirs = await BenchTools(sam.household_id, sam.person_id, bench.id).call(ToolCall("r", "bench_read", {}))
            assert theirs.is_error and theirs.content.startswith("not_found:")
            opened = await OpenBenchTools(alana.household_id, alana.person_id).call(
                ToolCall("o", "open_bench", {"title": "Garden"}))
            assert [b.title for b in await shop.open_benches(alana)][0] == "Garden" and not opened.is_error
        finally:
            await database.close()

    run(scenario())


def test_her_code_piece_is_a_code_kind_and_a_range_edit_of_a_long_one_is_logged_and_undoable(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    source = "".join(f"x{i} = {i}\n" for i in range(3000))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "shed")
            hers = BenchTools(alana.household_id, alana.person_id, bench.id)
            added = await hers.call(ToolCall("a", "bench_add", {"kind": "code", "title": "gen.py", "body": source}))
            assert not added.is_error, added.content
            piece_id = json.loads(added.content)["piece_id"]
            (made,) = (await shop.read(alana, bench.id)).pieces
            assert made.kind == "code" and len(made.text.body) > workshop_rules.load().kinds["note"].max_chars
            turn = BenchTools(alana.household_id, alana.person_id, bench.id)   # a later turn: nothing read yet
            window = await turn.call(ToolCall("r", "bench_read_piece", {"piece_id": piece_id, "offset": 20000}))
            assert json.loads(window.content)["offset"] == 20000
            replaced = await turn.call(ToolCall("p", "bench_replace", {"piece_id": piece_id, "base_version": 1,
                                                                       "old": "x2999 = 2999\n", "new": "done = 1\n"}))
            assert not replaced.is_error, replaced.content
            (after,) = (await shop.read(alana, bench.id)).pieces
            assert after.version == 2 and after.text.body == source.replace("x2999 = 2999\n", "done = 1\n")
            await shop.apply(alana, bench.id, Undo(By(alana.person_id), 2))
            (undone,) = (await shop.read(alana, bench.id)).pieces
            assert undone.text.body == source
        finally:
            await database.close()

    run(scenario())
