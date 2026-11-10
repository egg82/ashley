"""The Runs service for benches: a run tied to a bench command, the latest run of each piece, and the files a piece's
next run starts with. Households see only their own."""

import psycopg
import pytest
from ashley.runs.model import BenchRun, NewRun, Outcome, Output
from ashley.runs.runs import Runs
from brb_support import HER, RAN, World, add_code, out, run_cmd, world
from contract.conversations_support import run


async def bench_with_piece(w: World) -> tuple[int, int]:
    bench = await w.workshop.open(w.alana, "b")
    await w.workshop.apply(w.alana, bench.id, add_code(by=HER))
    return bench.id, 1


async def new(w: World, bench_id: int, piece: int = 1, version: int = 1, script: str = "s") -> NewRun:
    """A run of the piece made by a Run command that is logged on the bench, as a bench run's foreign key requires."""
    applied = await w.workshop.apply(w.alana, bench_id, run_cmd(piece, version, by=HER))
    assert applied.outcome == "accepted"
    return NewRun(w.alana.household_id, None, None, None, "python", script, "", {}, BenchRun(bench_id, applied.seq, piece, version))


async def done(w: World, n: NewRun, output: Output = RAN) -> int:
    run_id = await w.runs.start(n)
    await w.runs.finish(run_id, output)
    return run_id


def test_a_bench_run_without_a_turn_is_recorded_and_read_back_whole(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            run_id = await w.runs.start(await new(w, bench, piece, 1, "print(5)"))
            started = await w.runs.get(w.alana.household_id, run_id)
            assert started is not None and started.output is None and started.finished_at is None
            assert started.bench is not None and started.bench.piece_version == 1 and started.bench.piece_id == piece
            assert started.bench.bench_id == bench and started.script == "print(5)"
            assert (started.conversation_id, started.turn_id, started.call_id) == (None, None, None)
            finished = await w.runs.finish(run_id, RAN)
            assert finished.output == RAN and finished.finished_at is not None and finished.bench == started.bench

    run(scenario())


def test_ids_of_a_turn_are_given_together_or_not_at_all() -> None:
    for ids in [(1, None, None), (None, 1, None), (None, None, "c"), (1, 1, None), (1, None, "c"), (None, 1, "c")]:
        with pytest.raises(ValueError):
            NewRun(1, ids[0], ids[1], ids[2], "python", "s", bench=BenchRun(1, 1, 1, 1))


def test_a_run_needs_a_turn_a_bench_or_both() -> None:
    with pytest.raises(ValueError):
        NewRun(1, None, None, None, "python", "s")
    NewRun(1, 1, 1, "c", "python", "s")
    NewRun(1, None, None, None, "python", "s", bench=BenchRun(1, 1, 1, 1))
    NewRun(1, 1, 1, "c", "python", "s", bench=BenchRun(1, 1, 1, 1))


def test_the_latest_run_of_each_piece_by_piece_id(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, _ = await bench_with_piece(w)
            await w.workshop.apply(w.alana, bench, add_code("two", HER))
            first = await done(w, await new(w, bench, 1))
            second = await done(w, await new(w, bench, 1))
            other = await done(w, await new(w, bench, 2))
            got = await w.runs.last_on_bench(w.alana.household_id, bench)
            assert {k: v.id for k, v in got.items()} == {1: second, 2: other} and first not in {v.id for v in got.values()}

    run(scenario())


def test_the_latest_run_may_be_one_that_has_not_finished(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            await done(w, await new(w, bench))
            pending = await w.runs.start(await new(w, bench))
            got = await w.runs.last_on_bench(w.alana.household_id, bench)
            assert got[piece].id == pending and got[piece].output is None

    run(scenario())


def test_a_bench_without_runs_has_none_and_another_benchs_runs_are_not_its(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, _ = await bench_with_piece(w)
            elsewhere, _ = await bench_with_piece(w)
            await done(w, await new(w, elsewhere))
            assert dict(await w.runs.last_on_bench(w.alana.household_id, bench)) == {}

    run(scenario())


def test_a_run_of_a_turn_alone_is_not_a_bench_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            with psycopg.connect(db_url) as conn:
                conv = conn.execute("INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                                    (w.alana.household_id,)).fetchone()
                assert conv is not None
                turn = conn.execute("INSERT INTO turns (conversation_id, household_id, author, text) "
                                    "VALUES (%s, %s, 'person', 'x') RETURNING id", (conv[0], w.alana.household_id)).fetchone()
                assert turn is not None
            await done(w, NewRun(w.alana.household_id, conv[0], turn[0], "c", "python", "s", "", {"a": "b"}))
            assert dict(await w.runs.last_on_bench(w.alana.household_id, bench)) == {}
            assert dict(await w.runs.files_left(w.alana.household_id, bench, piece)) == {}

    run(scenario())


def test_another_household_sees_nothing_of_a_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            await done(w, await new(w, bench))
            assert dict(await w.runs.last_on_bench(w.zed.household_id, bench)) == {}
            assert dict(await w.runs.files_left(w.zed.household_id, bench, piece)) == {}
            assert len(await w.runs.last_on_bench(w.alana.household_id, bench)) == 1

    run(scenario())


def test_files_left_are_those_of_the_latest_run_that_ran_to_its_end(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            assert dict(await w.runs.files_left(w.alana.household_id, bench, piece)) == {}
            await done(w, await new(w, bench), out("ran", {"a": "1"}))
            await done(w, await new(w, bench), out("ran", {"b": "2"}))
            assert dict(await w.runs.files_left(w.alana.household_id, bench, piece)) == {"b": "2"}

    run(scenario())


def test_a_run_that_exited_non_zero_still_passes_its_files_on(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            await done(w, await new(w, bench), Output("ran", 3, "", "boom", False, {"x": "y"}, ()))
            assert dict(await w.runs.files_left(w.alana.household_id, bench, piece)) == {"x": "y"}

    run(scenario())


@pytest.mark.parametrize("outcome", ["timed_out", "out_of_memory", "failed", "unknown"])
def test_a_run_that_did_not_run_to_its_end_passes_nothing_on_and_does_not_reset(db_url: str, outcome: Outcome) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            await done(w, await new(w, bench), out("ran", {"keep": "me"}))
            await done(w, await new(w, bench), out(outcome, {"half": "writ"}))
            assert dict(await w.runs.files_left(w.alana.household_id, bench, piece)) == {"keep": "me"}

    run(scenario())


def test_a_run_never_recorded_passes_nothing_on(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            await done(w, await new(w, bench), out("ran", {"keep": "me"}))
            await w.runs.start(await new(w, bench))
            assert dict(await w.runs.files_left(w.alana.household_id, bench, piece)) == {"keep": "me"}

    run(scenario())


def test_a_ran_run_with_no_files_passes_on_none(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, piece = await bench_with_piece(w)
            await done(w, await new(w, bench), out("ran", {"old": "x"}))
            await done(w, await new(w, bench), out("ran", {}))
            assert dict(await w.runs.files_left(w.alana.household_id, bench, piece)) == {}

    run(scenario())


def test_files_are_kept_per_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench, _ = await bench_with_piece(w)
            await w.workshop.apply(w.alana, bench, add_code("two", HER))
            await done(w, await new(w, bench, 1), out("ran", {"one": "1"}))
            await done(w, await new(w, bench, 2), out("ran", {"two": "2"}))
            assert dict(await w.runs.files_left(w.alana.household_id, bench, 1)) == {"one": "1"}
            assert dict(await w.runs.files_left(w.alana.household_id, bench, 2)) == {"two": "2"}

    run(scenario())


def test_files_are_kept_per_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            a, _ = await bench_with_piece(w)
            b, _ = await bench_with_piece(w)
            await done(w, await new(w, a), out("ran", {"in-a": "1"}))
            assert dict(await w.runs.files_left(w.alana.household_id, b, 1)) == {}

    run(scenario())


def test_the_service_is_the_null_object_until_wired() -> None:
    async def scenario() -> None:
        with pytest.raises(Exception):
            await Runs.null().last_on_bench(1, 1)

    run(scenario())
