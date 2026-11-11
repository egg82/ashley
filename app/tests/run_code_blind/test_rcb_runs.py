"""Runs in Postgres: a run is recorded before it starts and again when it ends, and only its own household reads it."""

from datetime import timedelta

import pytest
from ashley.db.pool import PoolDatabase
from ashley.runs.model import NewRun, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import RunsUnavailable
from hypothesis import given, settings
from hypothesis import strategies as st
from rcb_support import run
from rcb_world import other_household, world

OUT = Output("ran", 0, "out", "err", False, {"r.txt": "é"}, ("b.bin",))


def test_a_started_run_is_stored_with_its_job_and_no_output(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            new = w.new("print(1)\n", "call-9", "in", {"a.txt": "x"})
            found = await w.runs.get(w.home, await w.runs.start(new))
            assert found is not None
            assert (found.household_id, found.conversation_id, found.turn_id) == (w.home, w.conversation, w.turn)
            assert (found.call_id, found.language, found.script, found.stdin) == ("call-9", "python", "print(1)\n", "in")
            assert dict(found.files) == {"a.txt": "x"}
            assert found.output is None and found.finished_at is None and found.started_at is not None

    run(scenario())


def test_each_start_has_its_own_id_and_runs_are_never_merged(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            ids = [await w.runs.start(w.new()) for _ in range(3)]
            assert len(set(ids)) == 3 and w.rows() == 3

    run(scenario())


def test_finishing_records_the_output_and_returns_the_whole_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new("s", "c", "i"))
            done = await w.runs.finish(run_id, OUT)
            assert done.id == run_id and done.script == "s" and done.stdin == "i"
            assert done.output == OUT
            assert done.finished_at is not None and done.finished_at >= done.started_at
            assert done.finished_at - done.started_at < timedelta(minutes=1)
            assert await w.runs.get(w.home, run_id) == done

    run(scenario())


@pytest.mark.parametrize("output", [Output("timed_out", None, "", ""), Output("out_of_memory", None, "", "", True),
                                    Output("failed", None, "x", "y"), Output("ran", -9, "", ""),
                                    Output("unknown", None, "", "")])
def test_every_kind_of_output_round_trips(db_url: str, output: Output) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new())
            await w.runs.finish(run_id, output)
            found = await w.runs.get(w.home, run_id)
            assert found is not None and found.output == output

    run(scenario())


def test_a_run_finishes_once(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new())
            first = await w.runs.finish(run_id, OUT)
            with pytest.raises(ValueError):
                await w.runs.finish(run_id, Output("failed", None, "other", ""))
            assert (await w.runs.get(w.home, run_id)) == first

    run(scenario())


def test_finishing_a_run_that_was_never_started_is_a_key_error(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            with pytest.raises(KeyError):
                await w.runs.finish(10_000, OUT)

    run(scenario())


def test_another_household_cannot_read_a_run_before_or_after_it_finishes(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            stranger = await other_household(w)
            run_id = await w.runs.start(w.new("SECRET"))
            assert await w.runs.get(stranger, run_id) is None
            await w.runs.finish(run_id, OUT)
            assert await w.runs.get(stranger, run_id) is None
            assert await w.runs.get(w.home, run_id) is not None
            assert await w.runs.get(w.home, run_id + 1) is None

    run(scenario())


def test_a_run_cannot_be_recorded_against_another_household_s_conversation(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            stranger = await other_household(w)
            bad = NewRun(stranger, w.conversation, w.turn, "c", "python", "s")
            with pytest.raises(Exception):
                await w.runs.start(bad)
            assert w.rows() == 0

    run(scenario())


@pytest.mark.parametrize("field", ["script", "stdin", "file_name", "file_text", "call_id"])
def test_text_postgres_cannot_store_is_refused_and_nothing_is_recorded(db_url: str, field: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bad = {"script": w.new("a\x00b"), "stdin": w.new(stdin="a\x00"), "file_name": w.new(files={"\x00": "x"}),
                   "file_text": w.new(files={"a": "\x00"}), "call_id": w.new(call_id="c\x00")}[field]
            with pytest.raises(ValueError):
                await w.runs.start(bad)
            assert w.rows() == 0

    run(scenario())


@pytest.mark.parametrize("output", [Output("ran", 0, "", "", False, {"\x00": "a"}),
                                    Output("ran", 0, "", "", False, {}, ("\x00",))])
def test_output_names_postgres_cannot_store_are_refused_and_the_run_stays_open(db_url: str, output: Output) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.new())
            with pytest.raises(ValueError):
                await w.runs.finish(run_id, output)
            open_run = await w.runs.get(w.home, run_id)
            assert open_run is not None and open_run.output is None
            await w.runs.finish(run_id, OUT)

    run(scenario())


def test_an_unreachable_database_is_runs_unavailable(db_url: str) -> None:
    async def scenario() -> None:
        db = PoolDatabase("postgresql://postgres:pg@127.0.0.1:1/none", connect_timeout_s=0.5)
        runs = PostgresRuns(db)
        new = NewRun(1, 1, 1, "c", "python", "s")
        with pytest.raises(RunsUnavailable):
            await runs.start(new)
        with pytest.raises(RunsUnavailable):
            await runs.get(1, 1)
        with pytest.raises(RunsUnavailable):
            await runs.finish(1, OUT)

    run(scenario())


clean = st.text(alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)), max_size=60)


def test_arbitrary_text_survives_a_round_trip_byte_for_byte(db_url: str) -> None:
    @given(clean, clean, st.dictionaries(clean, clean, max_size=3), clean, clean)
    @settings(max_examples=15, deadline=None)
    def check(script: str, stdin: str, files: dict[str, str], out: str, err: str) -> None:
        async def scenario() -> None:
            async with world(db_url) as w:
                run_id = await w.runs.start(w.new(script, "c", stdin, files))
                output = Output("ran", 0, out, err, False, files, tuple(files))
                await w.runs.finish(run_id, output)
                found = await w.runs.get(w.home, run_id)
                assert found is not None and found.output == output
                assert (found.script, found.stdin, dict(found.files)) == (script, stdin, files)

        run(scenario())

    check()
