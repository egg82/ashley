"""`Runs.in_conversation` over Postgres: one conversation's runs, oldest first, never a bench piece's."""

import pytest
from ashley.db.pool import PoolDatabase
from ashley.runs.model import NewRun
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import NullRuns, RunsUnavailable
from contract.conversations_support import household
from cr_support import OUT, run_async as run, world


def test_a_conversation_nothing_ran_in_has_no_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            conv = await w.conversation("t1")
            await w.said(conv)
            assert await w.runs.in_conversation(w.home, conv) == []

    run(scenario())


def test_the_runs_come_back_oldest_first_whichever_finished_first(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            conv = await w.conversation("t1")
            first, second = await w.said(conv), await w.said(conv)
            a = await w.runs.start(w.new(conv, first, "a"))
            b = await w.runs.start(w.new(conv, second, "b"))
            c = await w.runs.start(w.new(conv, first, "c"))
            await w.runs.finish(c, OUT)
            await w.runs.finish(a, OUT)
            got = await w.runs.in_conversation(w.home, conv)
            assert [r.id for r in got] == [a, b, c] == sorted([a, b, c])
            assert [r.script for r in got] == ["a", "b", "c"]

    run(scenario())


def test_a_run_still_going_and_a_finished_one_are_both_served_as_stored(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            conv = await w.conversation("t1")
            turn = await w.said(conv)
            going = await w.runs.start(w.new(conv, turn, "going"))
            done = await w.runs.start(w.new(conv, turn, "done"))
            await w.runs.finish(done, OUT)
            got = await w.runs.in_conversation(w.home, conv)
            assert [(r.id, r.output, r.turn_id, r.conversation_id) for r in got] == [
                (going, None, turn, conv), (done, OUT, turn, conv)]
            assert got[0].finished_at is None and got[1].finished_at is not None

    run(scenario())


def test_only_the_asked_conversations_runs_come_back(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            one, two = await w.conversation("t1"), await w.conversation("t2")
            t1, t2 = await w.said(one), await w.said(two)
            mine = await w.runs.start(w.new(one, t1, "mine"))
            theirs = await w.runs.start(w.new(two, t2, "theirs"))
            assert [r.id for r in await w.runs.in_conversation(w.home, one)] == [mine]
            assert [r.id for r in await w.runs.in_conversation(w.home, two)] == [theirs]

    run(scenario())


def test_another_household_reads_none_of_it_and_its_own_runs_stay_its_own(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            conv = await w.conversation("t1")
            await w.runs.start(w.new(conv, await w.said(conv), "SECRET"))
            stranger = household(db_url, "elsewhere")
            theirs = await w.conversation("t1", stranger)
            who = (await w.conversations.get(theirs))
            assert who is not None and who.household_id == stranger
            assert await w.runs.in_conversation(stranger, conv) == []
            assert await w.runs.in_conversation(stranger, theirs) == []
            assert [r.script for r in await w.runs.in_conversation(w.home, conv)] == ["SECRET"]
            assert await w.runs.in_conversation(w.home, theirs) == []

    run(scenario())


def test_a_run_made_by_a_bench_command_is_left_out_even_when_her_turn_asked(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            conv = await w.conversation("bench:1")
            turn = await w.said(conv)
            chat = await w.runs.start(w.new(conv, turn, "chat"))
            both = NewRun(w.home, conv, turn, "c-bench", "python", "bench_run", bench=w.bench(1))
            await w.runs.start(both)
            later = await w.runs.start(w.new(conv, turn, "later"))
            assert [r.id for r in await w.runs.in_conversation(w.home, conv)] == [chat, later]

    run(scenario())


def test_a_run_a_person_started_on_a_bench_is_in_no_conversation(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            conv = await w.conversation("bench:1")
            await w.said(conv)
            only = NewRun(w.home, None, None, None, "python", "pressed", bench=w.bench(1))
            await w.runs.start(only)
            assert await w.runs.in_conversation(w.home, conv) == []

    run(scenario())


def test_a_run_from_a_benchs_talk_without_a_bench_command_is_served(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            w.bench(1)
            talk = await w.conversation("bench:1")
            made = await w.runs.start(w.new(talk, await w.said(talk), "from the talk"))
            assert [r.id for r in await w.runs.in_conversation(w.home, talk)] == [made]

    run(scenario())


def test_an_unknown_conversation_has_no_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            assert await w.runs.in_conversation(w.home, 987654) == []

    run(scenario())


def test_an_unreachable_database_is_runs_unavailable(db_url: str) -> None:
    async def scenario() -> None:
        runs = PostgresRuns(PoolDatabase("postgresql://postgres:pg@127.0.0.1:1/none", connect_timeout_s=0.1))
        with pytest.raises(RunsUnavailable):
            await runs.in_conversation(1, 1)

    run(scenario())


def test_the_null_runs_serve_none() -> None:
    async def scenario() -> None:
        assert await NullRuns().in_conversation(1, 1) == []

    run(scenario())
