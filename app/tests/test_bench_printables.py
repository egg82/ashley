"""Her tools for a Printables design over the real Workshop, an in-memory object store, the real adapter and the
recorded API: she lists a model's files by a result number and puts one on the bench as a file piece, hers and
undoable, its bytes the design file's; each refusal is distinct and says why; no URL is ever an argument."""

import asyncio
import hashlib
import json
from typing import Any

import httpx2
import pytest
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person
from live_support import FakeLive
from page_support import html
from printables_support import (STEP_FILE, STL_FILE, THREE_MF_FILE, adapter, api, file_bytes, link_of, recorded)
from search_support import events

from ashley import logs, services
from ashley.db.pool import PoolDatabase
from ashley.files import config as files_config
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.printables.printables import NullPrintables, Printables
from ashley.tools import results
from ashley.tools.bench_printables import BenchPrintablesTools, is_model
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Undo
from ashley.workshop.model import By, Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop

RULES = workshop_rules.load()
KEYCHAIN, PEG, WASHER = ("https://www.printables.com/model/100101-k", "https://www.printables.com/model/100201-p",
                         "https://www.printables.com/model/100301-w")


def numbered() -> results.Results:
    store = results.Results()
    for url in (KEYCHAIN, PEG, WASHER, "https://example.org/page"):
        store.record(url)
    return store


async def say(tools: BenchPrintablesTools, name: str, **args: object) -> ToolResult:
    return await tools.call(ToolCall("c", name, args))


def outcome(got: ToolResult) -> str:
    assert got.is_error, got.content
    return got.content.split(":")[0]


class Bench:
    """A bench in a real Workshop with the recorded Printables wired as the service."""

    def __init__(self, db_url: str, answers: dict[str, Any] | None = None,
                 served: dict[str, httpx2.Response] | None = None) -> None:
        self.home = household(db_url)
        self.owner = Owner(self.home, person(db_url, self.home))
        self.database = PoolDatabase(db_url)
        self.store = MemoryStore()
        self.fake = api(answers or recorded(), served)
        self.tools: BenchPrintablesTools
        self.bench_id = 0

    async def __aenter__(self) -> "Bench":
        await self.database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(self.database, RULES))
        services.register(ObjectStore, self.store)
        services.register(Printables, adapter(self.fake))
        self.bench_id = (await services.get(Workshop).open(self.owner, "shed")).id
        self.tools = BenchPrintablesTools(self.home, self.owner.person_id, self.bench_id, numbered())
        return self

    async def __aexit__(self, *exc: object) -> None:
        services.unregister(Printables)
        await self.database.close()

    async def pieces(self) -> Any:
        return (await services.get(Workshop).read(self.owner, self.bench_id)).pieces


def test_the_tools_are_offered_only_where_a_store_and_printables_are_wired(db_url: str) -> None:
    async def run() -> None:
        async with Bench(db_url) as bench:
            assert [s.name for s in (await bench.tools.catalogue()).specs] == [
                "printables_files", "bench_add_printables_file"]
            services.register(ObjectStore, NullStore())
            assert (await bench.tools.catalogue()).specs == ()
            services.register(ObjectStore, bench.store)
            services.register(Printables, NullPrintables())
            assert (await bench.tools.catalogue()).specs == ()
    asyncio.run(run())


def test_she_lists_a_models_files_and_adds_each_kind_as_a_file_piece_of_the_files_own_bytes(db_url: str) -> None:
    async def run() -> None:
        async with Bench(db_url) as bench:
            listed = json.loads((await say(bench.tools, "printables_files", result=3)).content)
            assert listed["files"][0] == {"file": "200301", "name": "M5_Washer_OutsideDiameter10mm.stp",
                                          "size": 8927, "takes": True}
            assert all(f["takes"] for f in listed["files"])
            for result, file, name, media, data in ((1, STL_FILE, "base_letter_3mm.stl", "model/stl", "keychain.stl"),
                                                    (2, THREE_MF_FILE, "Shelf Support Peg.3mf", "model/3mf", "peg.3mf"),
                                                    (3, STEP_FILE, "M5_Washer_OutsideDiameter10mm.stp", "text/plain",
                                                     "washer.stp")):
                said = await say(bench.tools, "bench_add_printables_file", result=result, file=file)
                assert not said.is_error, said.content
                got = json.loads(said.content)
                assert (got["media_type"], got["size"]) == (media, len(file_bytes(data)))
                piece = next(p for p in await bench.pieces() if p.id == got["piece_id"])
                assert (piece.kind, piece.text.title) == ("file", name)
                assert json.loads(piece.text.body)["sha256"] == hashlib.sha256(file_bytes(data)).hexdigest()
            assert len(await bench.pieces()) == 3
    asyncio.run(run())


def test_the_add_is_hers_and_can_be_undone(db_url: str) -> None:
    async def run() -> None:
        async with Bench(db_url) as bench:
            got = json.loads((await say(bench.tools, "bench_add_printables_file", result=2, file=THREE_MF_FILE)).content)
            shop = services.get(Workshop)
            assert {row.by.author for row in await shop.log(bench.owner, bench.bench_id)} == {"ashley"}
            await shop.apply(bench.owner, bench.bench_id, Undo(By(bench.owner.person_id), got["seq"]))
            assert await bench.pieces() == ()
    asyncio.run(run())


def test_each_refusal_is_its_own_outcome(db_url: str) -> None:
    answers = recorded()
    listed = answers["detail-100301"]["data"]["print"]["stls"]
    listed += [{"id": "1", "name": "model.f3d", "fileSize": 100}, {"id": "2", "name": "Huge.STL", "fileSize": files_config.load().max_bytes + 1},
               {"id": "999999999", "name": "paid.stl", "fileSize": 100}, {"id": "3", "name": "page.stl", "fileSize": 100}]
    answers["link-3"] = {"data": {"getDownloadLink": {"ok": True, "output": {"link": "https://files.printables.com/x"}}}}
    answers["link-2"] = answers["link-1"] = answers["link-200301"]
    served = {"https://files.printables.com/x": html("<p>Just a moment...</p>")}

    async def run() -> None:
        async with Bench(db_url, answers, served) as bench:
            async def add(result: int, file: str) -> str:
                return outcome(await say(bench.tools, "bench_add_printables_file", result=result, file=file))
            assert await add(9, STEP_FILE) == "unknown_result"
            assert await add(4, STEP_FILE) == "not_a_model_page"
            assert await add(3, "424242") == "no_such_file"
            assert await add(3, "1") == "not_a_model"
            assert await add(3, "2") == "too_large"
            assert await add(3, "999999999") == "needs_login"
            assert await add(3, "3") == "not_a_model"
            assert await bench.pieces() == ()
            assert [json.loads(r.content)["variables"]["file"] for r in bench.fake.requests
                    if str(r.url).endswith("/graphql/") and "file" in json.loads(r.content)["variables"]] == ["999999999", "3"]
    asyncio.run(run())


def test_a_file_whose_bytes_are_not_the_kind_its_name_says_is_not_a_model(db_url: str) -> None:
    answers = recorded()
    answers["detail-100301"]["data"]["print"]["stls"][0]["name"] = "fake.3mf"
    answers["detail-100101"]["data"]["print"]["stls"] = [{"id": "5", "name": "fake.step", "fileSize": 700}]
    answers["link-5"] = answers[f"link-{STL_FILE}"]

    async def run() -> None:
        async with Bench(db_url, answers) as bench:
            assert outcome(await say(bench.tools, "bench_add_printables_file", result=3, file=STEP_FILE)) == "not_a_model"
            assert outcome(await say(bench.tools, "bench_add_printables_file", result=1, file="5")) == "not_a_model"
    asyncio.run(run())


def test_printables_failing_is_unavailable_and_adds_nothing(db_url: str) -> None:
    async def run() -> None:
        async with Bench(db_url, served={link_of(STL_FILE): httpx2.Response(503)}) as bench:
            assert outcome(await say(bench.tools, "bench_add_printables_file", result=1, file=STL_FILE)) == "unavailable"
            assert await bench.pieces() == ()
    asyncio.run(run())


@pytest.mark.parametrize("args", [{"result": 1, "file": STL_FILE, "url": "https://files.printables.com/x.stl"},
                                  {"result": "1", "file": STL_FILE}, {"result": 1}, {"file": STL_FILE}])
def test_a_url_is_not_an_argument_and_the_arguments_are_checked(db_url: str, args: dict[str, object]) -> None:
    async def run() -> None:
        async with Bench(db_url) as bench:
            assert outcome(await say(bench.tools, "bench_add_printables_file", **args)) == "bad_arguments"
            assert outcome(await say(bench.tools, "printables_files", **{k: v for k, v in args.items() if k != "file"}
                                     | {"url": "x"})) == "bad_arguments"
            assert bench.fake.requests == []
    asyncio.run(run())


def test_the_log_has_outcomes_and_sizes_and_never_a_name_or_a_link(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def run() -> None:
        async with Bench(db_url) as bench:
            capsys.readouterr()
            await say(bench.tools, "bench_add_printables_file", result=1, file=STL_FILE)
            await say(bench.tools, "bench_add_printables_file", result=3, file="424242")
    asyncio.run(run())
    out = capsys.readouterr().out
    done = events(out, "tools.call")
    assert [(e["outcome"], e.get("size")) for e in done] == [("ok", "684"), ("no_such_file", None)]
    assert "base_letter" not in out and "files.printables.com" not in out and "keychain" not in out


@pytest.mark.parametrize(("name", "data", "expected"), [
    ("a.stl", b"solid cube\nfacet normal 0 0 1\nendsolid cube\n", True),
    ("a.STL", b"  solid cube\nendsolid\n", True),
    ("a.stl", b"<html>Just a moment</html>", False),
    ("a.stl", b"", False),
    ("a.3mf", b"PK\x03\x04" + b"\x00" * 26, False),
    ("a.step", b"\r\n ISO-10303-21;\r\nHEADER;", True),
    ("a.step", b"solid cube\n", False),
    ("a.stp", b"<html>", False)])
def test_what_makes_a_download_the_kind_of_model_its_name_says(name: str, data: bytes, expected: bool) -> None:
    assert is_model(name, data) is expected
