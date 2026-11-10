"""`Runs.of_turns` over Postgres, and `NullRuns`."""

import psycopg
from ashley.runs.model import NewRun, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import NullRuns
from ashley.conversations.model import NewTurn
from ashley.db.pool import PoolDatabase
from ashley.conversations.postgres import PostgresConversations
from contract.conversations_support import POLICY, household, person, run


def test_the_null_runs_reads_nothing() -> None:
    async def scenario() -> None:
        assert await NullRuns().of_turns(1, (1, 2), 5) == []

    run(scenario())


def bench_run(url: str, home: int, conv: int, turn: int) -> None:
    """A run her turn asked for that a bench's Run command made, written past the bench foreign keys."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET session_replication_role = replica")
        conn.execute("INSERT INTO code_runs (household_id, conversation_id, turn_id, call_id, language, script, stdin, "
                     "files, bench_id, bench_seq, piece_id, piece_version) VALUES (%s, %s, %s, 'bc', 'python', 'b', "
                     "'', '{}', 1, 1, 1, 1)", (home, conv, turn))


async def _world(url: str) -> tuple[PoolDatabase, PostgresRuns, int, int, list[int], str]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    home = household(url)
    who = person(url, home)
    conversations = PostgresConversations(db, POLICY)
    conv = await conversations.for_thread(home, "t1", "chat", [who])
    turns = [(await conversations.add_turn(conv.id, NewTurn("person", f"q{i}", who))).id for i in range(3)]
    return db, PostgresRuns(db), home, conv.id, turns, url


def test_of_turns_gives_the_latest_runs_of_those_turns_oldest_first(db_url: str) -> None:
    async def scenario() -> None:
        db, runs, home, conv, turns, _ = await _world(db_url)
        try:
            ids: list[int] = []
            for i in range(4):
                ids.append(await runs.start(NewRun(home, conv, turns[i % 2], f"c{i}", "python", f"s{i}")))
            await runs.start(NewRun(home, conv, turns[2], "other", "python", "not asked for"))
            got = await runs.of_turns(home, (turns[0], turns[1]), 3)
            assert [r.id for r in got] == ids[1:]
            assert [r.id for r in await runs.of_turns(home, (turns[0], turns[1]), 10)] == ids
            assert [r.id for r in await runs.of_turns(home, (turns[0],), 10)] == [ids[0], ids[2]]
        finally:
            await db.close()

    run(scenario())


def test_of_turns_reads_nothing_for_zero_or_no_turns(db_url: str) -> None:
    async def scenario() -> None:
        db, runs, home, conv, turns, _ = await _world(db_url)
        try:
            await runs.start(NewRun(home, conv, turns[0], "c", "python", "s"))
            assert await runs.of_turns(home, (turns[0],), 0) == []
            assert await runs.of_turns(home, (), 5) == []
        finally:
            await db.close()

    run(scenario())


def test_of_turns_leaves_out_bench_runs_even_ones_her_turn_asked_for(db_url: str) -> None:
    async def scenario() -> None:
        db, runs, home, conv, turns, _ = await _world(db_url)
        try:
            plain = await runs.start(NewRun(home, conv, turns[0], "c1", "python", "s"))
            bench_run(db_url, home, conv, turns[0])
            assert [r.id for r in await runs.of_turns(home, (turns[0],), 5)] == [plain]
        finally:
            await db.close()

    run(scenario())


def test_of_turns_keeps_the_latest_by_id_among_non_bench_runs(db_url: str) -> None:
    async def scenario() -> None:
        db, runs, home, conv, turns, _ = await _world(db_url)
        try:
            a = await runs.start(NewRun(home, conv, turns[0], "c1", "python", "s"))
            b = await runs.start(NewRun(home, conv, turns[0], "c2", "python", "s"))
            bench_run(db_url, home, conv, turns[0])
            assert [r.id for r in await runs.of_turns(home, (turns[0],), 2)] == [a, b]
        finally:
            await db.close()

    run(scenario())


def test_of_turns_never_reads_another_households_runs(db_url: str) -> None:
    async def scenario() -> None:
        db, runs, home, conv, turns, url = await _world(db_url)
        try:
            await runs.start(NewRun(home, conv, turns[0], "c1", "python", "s"))
            elsewhere = household(url, "elsewhere")
            assert await runs.of_turns(elsewhere, (turns[0],), 5) == []
        finally:
            await db.close()

    run(scenario())


def test_of_turns_gives_the_stored_output_and_job(db_url: str) -> None:
    async def scenario() -> None:
        db, runs, home, conv, turns, _ = await _world(db_url)
        try:
            rid = await runs.start(NewRun(home, conv, turns[0], "c1", "python", "print(1)", "in", {"a": "b"}))
            await runs.finish(rid, Output("ran", 0, "1\n", ""))
            await runs.start(NewRun(home, conv, turns[0], "c2", "python", "unfinished"))
            first, second = await runs.of_turns(home, (turns[0],), 5)
            assert first.output == Output("ran", 0, "1\n", "") and first.script == "print(1)"
            assert second.output is None
        finally:
            await db.close()

    run(scenario())
