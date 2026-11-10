"""Her tools for files: `bench_add_file` makes a file piece from text under the name's type, checked against the bytes
like an upload and hers in the log; `bench_read_piece` reads a text file piece; `bench_read` shows a file's name, size
and type and never its hash; she cannot add a large piece with a body she wrote."""

import json

import pytest
from ashley import services
from ashley.files.intake import key_of
from ashley.files.store import NullStore, ObjectStore
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_files import BenchFileTools
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.model import HER, Text
from ashley.workshop.commands import Add
from ashley.workshop.stored_file import file_of
from files_blind_support import PNG, FakeStore, Env, env, go as run, sha

_n = iter(range(1, 10_000))


def call(tool: str, /, **args: object) -> ToolCall:
    return ToolCall(f"c{next(_n)}", tool, args)


def add_tools(e: Env, bench: int) -> BenchFileTools:
    return BenchFileTools(e.world.alana.household_id, e.world.alana.person_id, bench)


def read_tools(e: Env, bench: int) -> BenchTools:
    return BenchTools(e.world.alana.household_id, e.world.alana.person_id, bench)


async def opened(e: Env) -> int:
    return (await e.workshop.open(e.world.alana, "b")).id


def test_the_tool_is_offered_only_while_a_store_is_wired(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            offered = (await add_tools(e, bench).catalogue()).specs
            assert [s.name for s in offered] == ["bench_add_file"]
            services.register(ObjectStore, NullStore())
            assert (await add_tools(e, bench).catalogue()).specs == ()

    run(scenario())


def test_text_becomes_a_file_piece_typed_by_its_name_kept_in_the_store_and_hers(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            result = await add_tools(e, bench).call(call("bench_add_file", name="out.csv", text="a,b\n1,2\n"))
            assert not result.is_error
            piece = (await e.workshop.read(e.world.alana, bench)).pieces[0]
            f = file_of(piece.text.body)
            assert piece.kind == "file" and f is not None
            assert (f.name, f.media_type, f.size, f.sha256) == ("out.csv", "text/csv", 8, sha(b"a,b\n1,2\n"))
            assert e.store.held == {key_of(e.world.alana.household_id, f.sha256): b"a,b\n1,2\n"}
            assert str(piece.id) in result.content
            (row,) = await e.workshop.log(e.world.alana, bench)
            assert (row.by.author, row.outcome) == ("ashley", "accepted")

    run(scenario())


@pytest.mark.parametrize(("name", "media"), [("notes.md", "text/markdown"), ("data.json", "application/json"), ("plain.txt", "text/plain")])
def test_the_extension_picks_the_text_type(db_url: str, name: str, media: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            assert not (await add_tools(e, bench).call(call("bench_add_file", name=name, text='{"a": 1}'))).is_error
            f = file_of((await e.workshop.read(e.world.alana, bench)).pieces[0].text.body)
            assert f is not None and f.media_type == media

    run(scenario())


def refused_adds_nothing(e: Env, result: ToolResult, bench: int):
    async def check() -> None:
        assert result.is_error
        assert not (await e.workshop.read(e.world.alana, bench)).pieces

    return check()


def test_text_under_a_name_that_says_it_is_something_else_is_an_error_and_adds_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            for name in ("fake.png", "fake.pdf"):
                r = await add_tools(e, bench).call(call("bench_add_file", name=name, text="just words"))
                await refused_adds_nothing(e, r, bench)
            assert e.store.held == {}

    run(scenario())


def test_empty_text_and_bad_arguments_are_error_results_not_exceptions(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            t = add_tools(e, bench)
            for args in ({"name": "a.txt", "text": ""}, {"name": "a.txt"}, {"text": "x"}, {"name": "a.txt", "text": "x", "bogus": 1},
                         {"name": "a.txt", "from_piece": 999}):
                await refused_adds_nothing(e, await t.call(call("bench_add_file", **args)), bench)
            await refused_adds_nothing(e, await t.call(call("nonesuch", name="a.txt", text="x")), bench)

    run(scenario())


def test_an_unreachable_store_is_an_error_result_and_adds_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url, FakeStore(down=True)) as e:
            bench = await opened(e)
            r = await add_tools(e, bench).call(call("bench_add_file", name="a.txt", text="x"))
            await refused_adds_nothing(e, r, bench)

    run(scenario())


def test_text_too_large_for_a_bench_is_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            from files_blind_support import CONFIG
            r = await add_tools(e, bench).call(call("bench_add_file", name="big.txt", text="a" * (CONFIG.max_bytes + 1)))
            await refused_adds_nothing(e, r, bench)

    run(scenario())


def test_she_reads_a_text_file_piece_and_its_text_is_in_the_result(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            await add_tools(e, bench).call(call("bench_add_file", name="story.txt", text="once upon a time, a café"))
            piece = (await e.workshop.read(e.world.alana, bench)).pieces[0]
            r = await read_tools(e, bench).call(call("bench_read_piece", piece_id=piece.id))
            assert not r.is_error and "once upon a time, a caf\u00e9" in json.loads(r.content)["body"]

    run(scenario())


def test_a_long_text_file_is_read_in_windows_from_an_offset(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            text = "".join(f"line {i:05d}\n" for i in range(3000))
            await add_tools(e, bench).call(call("bench_add_file", name="long.txt", text=text))
            piece = (await e.workshop.read(e.world.alana, bench)).pieces[0]
            first = await read_tools(e, bench).call(call("bench_read_piece", piece_id=piece.id))
            assert "line 00000" in first.content and "line 02999" not in first.content
            last = await read_tools(e, bench).call(call("bench_read_piece", piece_id=piece.id, offset=len(text) - 40))
            assert "line 02999" in last.content and "line 00000" not in last.content

    run(scenario())


def test_bench_read_shows_a_files_name_size_and_type_and_never_its_hash(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            text = "x,y\n1,2\n"
            await add_tools(e, bench).call(call("bench_add_file", name="table.csv", text=text))
            await e.workshop.apply(e.world.alana, bench, Add(HER, "note", Text("n", "hi"), "small"))
            r = await read_tools(e, bench).call(call("bench_read"))
            assert "table.csv" in r.content and "text/csv" in r.content and str(len(text)) in r.content
            assert sha(text.encode()) not in r.content
            one = await read_tools(e, bench).call(call("bench_read_piece", piece_id=1))
            assert sha(text.encode()) not in one.content

    run(scenario())


def test_a_binary_file_piece_reads_without_its_bytes_or_hash(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            from ashley.workshop.bench_file import add_file
            from ashley.workshop import rules as workshop_rules
            from files_blind_support import by
            a = e.world.alana
            bench = await opened(e)
            await add_file(a, bench, by(a), PNG, "pic.png", "", workshop_rules.load())
            piece = (await e.workshop.read(a, bench)).pieces[0]
            for tool, args in (("bench_read", {}), ("bench_read_piece", {"piece_id": piece.id})):
                r = await read_tools(e, bench).call(call(tool, **args))
                assert sha(PNG) not in r.content and "IHDR" not in r.content and "pic.png" in r.content

    run(scenario())


@pytest.mark.parametrize("kind", ["file", "image"])
def test_she_cannot_add_a_large_piece_with_a_body_she_wrote(db_url: str, kind: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e)
            r = await read_tools(e, bench).call(call("bench_add", kind=kind, title="t", body="{}"))
            await refused_adds_nothing(e, r, bench)
            from ashley.workshop.stored_file import StoredFile, body_of
            made = body_of(StoredFile(sha(b"q"), 1, "image/png", "q.png"))
            r = await read_tools(e, bench).call(call("bench_add", kind=kind, title="t", body=made))
            await refused_adds_nothing(e, r, bench)

    run(scenario())
