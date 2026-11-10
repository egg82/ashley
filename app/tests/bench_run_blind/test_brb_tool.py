"""Her `bench_run` (a change) and `bench_last_run` (a read): offered only while the sandbox runs a language, the run
made by her and recorded against the bench, piece and her turn, errors and never an exception."""

import pytest
from ashley import services
from ashley.inference.model import ToolCall
from ashley.runs.sandbox import Sandbox
from ashley.tools.bench_run import BenchRunTools
from ashley.workshop.commands import Run
from ashley.workshop.model import HER as HER_BY
from ashley.workshop.model import Owner
from ashley.workshop.run_piece import run_piece
from brb_support import Box, World, add_code, add_note, by, out, run_cmd, world
from contract.conversations_support import run, scalar


def turn_of(url: str, owner: Owner) -> tuple[int, int]:
    conv = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                      (owner.household_id,)))
    turn = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                      "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conv, owner.household_id)))
    return conv, turn


def tools(w: World, url: str, bench: int, owner: Owner | None = None) -> BenchRunTools:
    who = owner or w.alana
    conv, turn = turn_of(url, who)
    return BenchRunTools(who.household_id, who.person_id, bench, conv, turn)


def call(name: str, **args: object) -> ToolCall:
    return ToolCall("call-1", name, args)


def go(piece: object = 1, version: object = 1, language: object = "python", **more: object) -> ToolCall:
    return call("bench_run", piece_id=piece, base_version=version, language=language, **more)


async def bench_with_code(w: World, body: str = "print(1)") -> int:
    bench = await w.workshop.open(w.alana, "b")
    await w.workshop.apply(w.alana, bench.id, add_code(body, by(w.alana)))
    return bench.id


def test_with_a_sandbox_that_runs_nothing_nothing_is_offered(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box(offered=())) as w:
            bench = await bench_with_code(w)
            assert (await tools(w, db_url, bench).catalogue()).specs == ()

    run(scenario())


def test_with_the_null_sandbox_nothing_is_offered(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            services.register(Sandbox, Sandbox.null())
            assert (await tools(w, db_url, bench).catalogue()).specs == ()

    run(scenario())


def test_a_run_is_a_change_and_the_last_run_is_a_read(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            specs = {spec.name: spec for spec in (await tools(w, db_url, bench).catalogue()).specs}
            assert set(specs) == {"bench_run", "bench_last_run"}
            assert specs["bench_run"].reads is False and specs["bench_last_run"].reads is True

    run(scenario())


def test_her_run_returns_what_came_out_and_is_recorded_against_bench_piece_and_her_turn(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w, "print('hi')")
            conv, turn = turn_of(db_url, w.alana)
            t = BenchRunTools(w.alana.household_id, w.alana.person_id, bench, conv, turn)
            got = await t.call(ToolCall("c-5", "bench_run", {"piece_id": 1, "base_version": 1, "language": "python"}))
            assert not got.is_error and got.call_id == "c-5"
            assert "OUT-A" in got.content and "S1" in got.content
            [job] = w.box.jobs
            assert job.script == "print('hi')" and job.language == "python"
            last = (await w.runs.last_on_bench(w.alana.household_id, bench))[1]
            assert last.output is not None and last.bench is not None
            assert (last.bench.bench_id, last.bench.piece_id, last.bench.piece_version) == (bench, 1, 1)
            assert (last.conversation_id, last.turn_id, last.call_id) == (conv, turn, "c-5")
            logged = (await w.workshop.log(w.alana, bench))[-1]
            assert logged.outcome == "accepted" and logged.command == Run(HER_BY, 1, 1, "python")

    run(scenario())


def test_her_run_starts_with_the_files_a_persons_run_left(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", {"p": "from-person"}), out("ran")])) as w:
            bench = await bench_with_code(w)
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            await tools(w, db_url, bench).call(go())
            assert dict(w.box.jobs[-1].files) == {"p": "from-person"}

    run(scenario())


def test_her_last_run_shows_whoever_ran_it(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", {"f": "FILE-Q"}, "PRINTED-Q")])) as w:
            bench = await bench_with_code(w)
            t = tools(w, db_url, bench)
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            got = await t.call(call("bench_last_run", piece_id=1))
            assert not got.is_error and "PRINTED-Q" in got.content and "FILE-Q" in got.content
            assert len(w.box.jobs) == 1

    run(scenario())


def test_the_last_run_of_a_piece_never_run_is_not_an_error_and_shows_no_output(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            got = await tools(w, db_url, bench).call(call("bench_last_run", piece_id=1))
            assert not got.is_error and "OUT-A" not in got.content and w.box.jobs == []

    run(scenario())


def test_the_last_run_is_the_latest_not_the_first(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", stdout="FIRST-Q"), out("ran", stdout="SECOND-Q")])) as w:
            bench = await bench_with_code(w)
            t = tools(w, db_url, bench)
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            await t.call(go())
            got = await t.call(call("bench_last_run", piece_id=1))
            assert "SECOND-Q" in got.content and "FIRST-Q" not in got.content

    run(scenario())


@pytest.mark.parametrize("arguments", [
    dict(piece=1, version=1, language="cobol"),
    dict(piece=1, version=9),
    dict(piece=7),
    dict(piece="1"),
    dict(piece=1, version="1"),
    dict(piece=1, language=None),
    dict(piece=1, stdin="x"),
])
def test_a_run_that_does_not_happen_is_an_error_result_and_nothing_runs(db_url: str, arguments: dict[str, object]) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            more = {k: v for k, v in arguments.items() if k not in ("piece", "version", "language")}
            got = await tools(w, db_url, bench).call(
                go(arguments["piece"], arguments.get("version", 1), arguments.get("language", "python"), **more))
            assert got.is_error and w.box.jobs == []
            assert scalar(db_url, "SELECT count(*) FROM code_runs") == 0

    run(scenario())


def test_a_missing_argument_is_an_error_result(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            t = tools(w, db_url, bench)
            for args in ({}, {"piece_id": 1}, {"piece_id": 1, "base_version": 1}):
                assert (await t.call(call("bench_run", **args))).is_error
            assert (await t.call(call("bench_last_run"))).is_error and w.box.jobs == []

    run(scenario())


def test_a_note_is_not_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = (await w.workshop.open(w.alana, "b")).id
            await w.workshop.apply(w.alana, bench, add_note(by(w.alana)))
            got = await tools(w, db_url, bench).call(go())
            assert got.is_error and w.box.jobs == []
            assert (await w.workshop.log(w.alana, bench))[-1].outcome == "not_runnable"

    run(scenario())


@pytest.mark.parametrize(("piece", "version", "why"), [(2, 1, "not_runnable"), (1, 9, "stale_base"), (8, 1, "no_such_piece")])
def test_a_refused_run_says_the_reason(db_url: str, piece: int, version: int, why: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            await w.workshop.apply(w.alana, bench, add_note(by(w.alana)))
            got = await tools(w, db_url, bench).call(go(piece, version))
            assert got.is_error and why in got.content and w.box.jobs == []

    run(scenario())


def test_the_last_run_is_of_the_piece_asked_for(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", stdout="TWO-Q")])) as w:
            bench = await bench_with_code(w)
            await w.workshop.apply(w.alana, bench, add_code("print(2)", by(w.alana)))
            t = tools(w, db_url, bench)
            await run_piece(w.alana, bench, run_cmd(2, by=by(w.alana)))
            assert "TWO-Q" in (await t.call(call("bench_last_run", piece_id=2))).content
            assert "TWO-Q" not in (await t.call(call("bench_last_run", piece_id=1))).content

    run(scenario())


def test_a_blank_piece_is_an_error_and_nothing_is_logged(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w, "  ")
            got = await tools(w, db_url, bench).call(go())
            assert got.is_error and w.box.jobs == [] and len(await w.workshop.log(w.alana, bench)) == 1

    run(scenario())


def test_an_unreachable_sandbox_is_an_error_not_an_exception(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box(down=True)) as w:
            bench = await bench_with_code(w)
            got = await tools(w, db_url, bench).call(go())
            assert got.is_error

    run(scenario())


def test_a_bench_that_is_not_hers_to_run_is_an_error_not_an_exception(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            for stranger in (w.sam, w.zed):
                got = await tools(w, db_url, bench, stranger).call(go())
                assert got.is_error
            closed = await bench_with_code(w)
            await w.workshop.close(w.alana, closed)
            assert (await tools(w, db_url, closed).call(go())).is_error
            assert w.box.jobs == []

    run(scenario())


@pytest.mark.parametrize("who", ["sam", "zed"])
def test_a_strangers_last_run_read_shows_nothing_of_the_owners_run(db_url: str, who: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", {"f": "SECRET-F"}, "SECRET-OUT")])) as w:
            bench = await bench_with_code(w)
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            stranger = w.sam if who == "sam" else w.zed
            got = await tools(w, db_url, bench, stranger).call(call("bench_last_run", piece_id=1))
            assert "SECRET" not in got.content

    run(scenario())
