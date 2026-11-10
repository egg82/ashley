"""Her side of files over the real Workshop and an in-memory object store: she adds a file from text she writes or from
what a code piece's latest run gave (its output, or a file it left), as a piece that is hers and undoable; she reads a
text file piece in windows and sees a binary one by name, size and type only; she cannot write an image or file body
herself; what the store or the bench refuses comes back as an error naming why; logs carry no name or content."""

import dataclasses
import json
from collections.abc import Mapping
from datetime import UTC, datetime

import pytest
from files_support import CSV, PDF
from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.files import config as files_config
from ashley.files.intake import Refused
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.runs.model import BenchRun, Output, Run
from ashley.runs.runs import NullRuns, Runs
from ashley.tools.bench_files import BenchFileTools
from ashley.tools.bench_tools import BenchTools
from ashley.workshop import rules as workshop_rules
from ashley.workshop.bench_file import add_file
from ashley.workshop.commands import Undo
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive

NOW = datetime(2026, 11, 1, tzinfo=UTC)
RULES = workshop_rules.load()


class OneRun(NullRuns):
    def __init__(self, latest: Run) -> None:
        self._latest = latest

    async def last_on_bench(self, household_id: int, bench_id: int) -> Mapping[int, Run]:
        bench = self._latest.bench
        return {} if bench is None else {bench.piece_id: self._latest}


def ran(piece: int, stdout: str, files: dict[str, str] | None = None) -> Run:
    return Run(1, 1, None, None, None, "python", "print()", "", {}, NOW, NOW,
               Output("ran", 0, stdout, "", files=files or {}), BenchRun(1, 2, piece, 1))


async def say(tools: BenchFileTools | BenchTools, name: str, args: dict[str, object]) -> ToolResult:
    return await tools.call(ToolCall("c", name, args))


def test_she_adds_a_file_from_text_or_a_runs_output_and_reads_a_text_file_back(db_url: str,
                                                                              capsys: object) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, RULES))
        store = MemoryStore()
        services.register(ObjectStore, store)
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "shed")
            files = BenchFileTools(home, alana.person_id, bench.id)
            hers = BenchTools(home, alana.person_id, bench.id)
            catalogue = await files.catalogue()
            assert [s.name for s in catalogue.specs] == ["bench_add_file"]

            made = await say(files, "bench_add_file", {"name": "cuts.csv", "text": "part,len\nrail,420\n"})
            assert not made.is_error, made.content
            body = json.loads(made.content)
            assert body["media_type"] == "text/csv" and body["size"] == 18
            (piece,) = (await shop.read(alana, bench.id)).pieces
            assert (piece.kind, piece.text.title) == ("file", "cuts.csv")

            read = json.loads((await say(hers, "bench_read_piece", {"piece_id": piece.id})).content)
            assert read["body"] == "part,len\nrail,420\n" and read["body_cut"] is False
            window = json.loads((await say(hers, "bench_read_piece", {"piece_id": piece.id, "offset": 9})).content)
            assert window["body"] == "rail,420\n" and window["offset"] == 9
            overview = json.loads((await say(hers, "bench_read", {})).content)
            assert json.loads(overview["pieces"][0]["body"]) == {"name": "cuts.csv", "size": 18, "media_type": "text/csv"}
            assert "sha256" not in json.dumps(overview)

            services.register(Runs, OneRun(ran(99, "printed\n", {"out.json": '{"ok": true}'})))
            first = await say(files, "bench_add_file", {"name": "log.txt", "from_piece": 99})
            assert not first.is_error, first.content
            output = json.loads(first.content)
            left = json.loads((await say(files, "bench_add_file", {
                "name": "out.json", "from_piece": 99, "file": "out.json"})).content)
            assert (output["media_type"], left["media_type"]) == ("text/plain", "application/json")
            pieces = (await shop.read(alana, bench.id)).pieces
            assert [p.text.title for p in pieces] == ["cuts.csv", "log.txt", "out.json"]
            texts = [json.loads((await say(hers, "bench_read_piece", {"piece_id": p.id})).content)["body"] for p in pieces]
            assert texts[1:] == ["printed\n", '{"ok": true}']

            log = await shop.log(alana, bench.id)
            assert {row.by.author for row in log} == {"ashley"}
            await shop.apply(alana, bench.id, Undo(By(alana.person_id), left["seq"]))
            assert [p.text.title for p in (await shop.read(alana, bench.id)).pieces] == ["cuts.csv", "log.txt"]
        finally:
            await database.close()

    run(scenario())


def test_what_she_cannot_do_is_an_error_that_says_why(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, RULES))
        services.register(ObjectStore, MemoryStore())
        services.register(Runs, OneRun(ran(5, "x")))
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "shed")
            files = BenchFileTools(home, alana.person_id, bench.id)
            hers = BenchTools(home, alana.person_id, bench.id)

            async def err(tools: BenchFileTools | BenchTools, name: str, args: dict[str, object]) -> str:
                got = await say(tools, name, args)
                assert got.is_error, got.content
                return got.content.split(":")[0]

            assert await err(files, "bench_add_file", {"name": "a.txt"}) == "bad_arguments"
            assert await err(files, "bench_add_file", {"name": "a.txt", "text": "x", "from_piece": 1}) == "bad_arguments"
            assert await err(files, "bench_add_file", {"name": "a.txt", "from_piece": 1}) == "bad_arguments"
            assert await err(files, "bench_add_file", {"name": "a.txt", "text": ""}) == "empty"
            assert await err(files, "bench_add_file", {"name": "a.png", "text": "not a picture"}) == "type_mismatch"
            assert await err(files, "bench_add_file", {"name": "a.txt", "text": "x\x00y"}) == "type_not_allowed"
            assert await err(files, "bench_add_file", {"name": "a.txt", "text": "x", "colour": 1}) == "bad_arguments"
            assert await err(hers, "bench_add", {"kind": "file", "title": "forged", "body": "{}"}) == "bad_file"
            well_formed = json.dumps({"sha256": "ab" * 32, "size": 5, "media_type": "application/pdf", "name": "x.pdf"})
            assert await err(hers, "bench_add", {"kind": "file", "title": "forged", "body": well_formed}) == "bad_file"
            assert (await shop.log(alana, bench.id)) == []
            assert (await shop.read(alana, bench.id)).pieces == ()
            services.register(ObjectStore, MemoryStore())
            stored, applied = await add_file(alana, bench.id, By(alana.person_id), PDF, "plan.pdf", "", RULES)
            assert applied.outcome == "accepted"
            piece = (await shop.read(alana, bench.id)).pieces[0]
            assert await err(hers, "bench_edit", {"piece_id": piece.id, "base_version": 1, "title": "plan.pdf",
                                                  "body": "{}"}) in ("unread", "bad_file")
            binary = json.loads((await say(hers, "bench_read_piece", {"piece_id": piece.id})).content)
            assert json.loads(binary["body"])["media_type"] == "application/pdf" and stored.size == len(PDF)
            store = MemoryStore()
            services.register(ObjectStore, store)
            _, text_applied = await add_file(alana, bench.id, By(alana.person_id), CSV, "a.csv", "", RULES)
            store.down = True
            assert await err(files, "bench_add_file", {"name": "b.txt", "text": "x"}) == "unavailable"
            assert await err(hers, "bench_read_piece", {"piece_id": text_applied.piece_id}) == "unavailable"
            assert not (await say(hers, "bench_read_piece", {"piece_id": piece.id})).is_error
        finally:
            await database.close()

    run(scenario())


def test_a_file_over_the_limit_is_refused_whoever_adds_it(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, RULES))
        store = MemoryStore()
        services.register(ObjectStore, store)
        try:
            bench = await services.get(Workshop).open(alana, "shed")
            small = dataclasses.replace(files_config.load(), max_bytes=len(CSV) - 1)
            with pytest.raises(Refused) as refused:
                await add_file(alana, bench.id, By(alana.person_id), CSV, "a.csv", "", RULES, small)
            assert refused.value.reason == "too_large" and store.objects == {}
        finally:
            await database.close()

    run(scenario())


def test_without_an_object_store_she_is_offered_no_file_tool(db_url: str) -> None:
    async def scenario() -> None:
        assert isinstance(services.get(ObjectStore), NullStore)
        assert (await BenchFileTools(1, 1, 1).catalogue()).specs == ()

    run(scenario())
