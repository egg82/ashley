"""Runs over a real database: a run is recorded before it runs and finished once, read back whole, only by its own
household; a run goes when the turn that asked for it goes; nothing of a script or output reaches the logs."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from ashley import logs
from ashley.db.pool import PoolDatabase
from ashley.runs.model import NewRun, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, run, scalar

SECRET = "print('plans-for-the-shed')"


@asynccontextmanager
async def runs_on(url: str) -> AsyncGenerator[Runs]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresRuns(database)
    finally:
        await database.close()


def turn(url: str) -> NewRun:
    home = household(url)
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    said = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "VALUES (%s, %s, 'person', 'add these') RETURNING id", (conversation, home)))
    return NewRun(home, conversation, said, "call-1", "python", SECRET, "1 2", {"in.txt": "x"})


def test_a_run_is_started_then_finished_once_and_read_back_whole(db_url: str) -> None:
    new = turn(db_url)
    output = Output("ran", 0, "3\n", "", False, {"out.txt": "3"}, ("big.bin",))

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            run_id = await runs.start(new)
            running = await runs.get(new.household_id, run_id)
            assert running is not None and running.output is None and running.finished_at is None
            assert (running.script, running.stdin, running.files, running.turn_id) == (SECRET, "1 2", {"in.txt": "x"},
                                                                                        new.turn_id)
            done = await runs.finish(run_id, output)
            assert done.output == output and done.finished_at is not None
            assert await runs.get(new.household_id, run_id) == done
            with pytest.raises(ValueError):
                await runs.finish(run_id, output)
            with pytest.raises(KeyError):
                await runs.finish(run_id + 1000, output)
            assert await runs.get(new.household_id + 1000, run_id) is None

    run(scenario())


def test_a_run_goes_with_the_turn_that_asked_for_it(db_url: str) -> None:
    new = turn(db_url)

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            run_id = await runs.start(new)
            scalar(db_url, "DELETE FROM turns WHERE id = %s RETURNING id", (new.turn_id,))
            assert await runs.get(new.household_id, run_id) is None

    run(scenario())


def test_text_with_a_nul_is_refused_before_the_database(db_url: str) -> None:
    new = turn(db_url)

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            with pytest.raises(ValueError):
                await runs.start(NewRun(new.household_id, new.conversation_id, new.turn_id, "c", "python", "a\x00"))
            run_id = await runs.start(new)
            with pytest.raises(ValueError):
                await runs.finish(run_id, Output("ran", 0, "\x00", ""))

    run(scenario())


@pytest.mark.xfail(strict=True, reason="a run's output holding a NUL is refused, losing the whole run record")
def test_output_with_a_nul_is_stored_with_the_nul_removed(db_url: str) -> None:
    new = turn(db_url)
    output = Output("ran", 0, "a\x00b", "c\x00", False, {"o\x00.bin": "x\x00y"}, ("s\x00.bin",))

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            done = await runs.finish(await runs.start(new), output)
            assert done.output == Output("ran", 0, "ab", "c", False, {"o.bin": "xy"}, ("s.bin",))

    run(scenario())


def test_logs_carry_ids_and_outcomes_never_the_script_or_output(db_url: str,
                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    new = turn(db_url)

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            run_id = await runs.start(new)
            await runs.finish(run_id, Output("ran", 0, "plans-for-the-shed", ""))

    run(scenario())
    out = capsys.readouterr().out
    assert "event=runs.started" in out and "event=runs.finished" in out
    assert "plans-for-the-shed" not in out and "1 2" not in out


def test_a_conversations_runs_come_in_one_read_oldest_first_and_only_its_own(db_url: str) -> None:
    mine, other = turn(db_url), turn(db_url)

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            first = await runs.start(mine)
            await runs.start(other)
            second = await runs.start(NewRun(mine.household_id, mine.conversation_id, mine.turn_id, "call-2", "python", "b"))
            await runs.finish(first, Output("timed_out", None, "x", "", True))
            assert mine.conversation_id is not None
            got = await runs.in_conversation(mine.household_id, mine.conversation_id)
            assert [r.id for r in got] == [first, second]
            assert got[0].output is not None and got[0].output.outcome == "timed_out" and got[1].output is None
            assert await runs.in_conversation(mine.household_id + 1000, mine.conversation_id) == []

    run(scenario())


def test_the_latest_runs_of_some_turns_come_in_one_read_oldest_first_for_its_household_alone(db_url: str) -> None:
    mine, other = turn(db_url), turn(db_url)

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            first = await runs.start(mine)
            await runs.start(other)
            second = await runs.start(NewRun(mine.household_id, mine.conversation_id, mine.turn_id, "call-2", "python", "b"))
            third = await runs.start(NewRun(mine.household_id, mine.conversation_id, mine.turn_id, "call-3", "python", "c"))
            assert mine.turn_id is not None and other.turn_id is not None
            asked = (mine.turn_id, other.turn_id)
            assert [r.id for r in await runs.of_turns(mine.household_id, asked, 5)] == [first, second, third]
            assert [r.id for r in await runs.of_turns(mine.household_id, asked, 2)] == [second, third]
            assert await runs.of_turns(mine.household_id, asked, 0) == []
            assert await runs.of_turns(mine.household_id, (), 5) == []
            assert await runs.of_turns(mine.household_id + 1000, asked, 5) == []

    run(scenario())


def test_a_build123d_run_is_recorded_and_read_back_and_an_unknown_language_is_refused(db_url: str) -> None:
    base = turn(db_url)
    new = NewRun(base.household_id, base.conversation_id, base.turn_id, "call-2", "build123d", "show(Box(1, 1, 1))")

    async def scenario() -> None:
        async with runs_on(db_url) as runs:
            run_id = await runs.start(new)
            got = await runs.get(new.household_id, run_id)
            assert got is not None and got.language == "build123d"

    run(scenario())
    with pytest.raises(Exception, match="code_runs_language_check"):
        scalar(db_url, "INSERT INTO code_runs (household_id, conversation_id, turn_id, call_id, language, script, stdin, "
                       "files) VALUES (%s, %s, %s, 'c', 'ruby', 'x', '', '{}') RETURNING id",
               (base.household_id, base.conversation_id, base.turn_id))
