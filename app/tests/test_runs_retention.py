"""A bench piece keeps its latest run and its latest run that ran to its end; its older runs go in the transaction
that records a bench run's result. A run asked for by a chat turn is kept as long as its conversation."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from ashley import logs
from ashley.db.pool import PoolDatabase
from ashley.runs.model import BenchRun, NewRun, Outcome, Output
from ashley.runs.postgres import PostgresRuns
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Run
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar

HER = By(None)


def output(outcome: Outcome, files: dict[str, str] | None = None) -> Output:
    return Output(outcome, 0 if outcome == "ran" else None, "", "", False, files or {}, ())


class Rig:
    def __init__(self, url: str, database: PoolDatabase) -> None:
        self.url = url
        self.runs = PostgresRuns(database)
        self.shop = PostgresWorkshop(database, workshop_rules.load())
        home = household(url)
        self.owner = Owner(home, person(url, home))
        self.bench = 0

    async def open(self) -> int:
        self.bench = (await self.shop.open(self.owner, "b")).id
        return self.bench

    async def piece(self) -> int:
        applied = await self.shop.apply(self.owner, self.bench, Add(HER, "code", Text("c", "print(1)"), "small"))
        assert applied.piece_id is not None
        return applied.piece_id

    async def started(self, piece: int) -> int:
        applied = await self.shop.apply(self.owner, self.bench, Run(HER, piece, 1, "python"))
        assert applied.outcome == "accepted"
        new = NewRun(self.owner.household_id, None, None, None, "python", "s", "", {},
                     BenchRun(self.bench, applied.seq, piece, 1))
        return await self.runs.start(new)

    async def finished(self, piece: int, outcome: Outcome = "ran", files: dict[str, str] | None = None) -> int:
        run_id = await self.started(piece)
        await self.runs.finish(run_id, output(outcome, files))
        return run_id

    def ids(self, piece: int | None = None) -> list[int]:
        rows = scalar(self.url, "SELECT coalesce(json_agg(id ORDER BY id), '[]'::json)::text FROM code_runs "
                                "WHERE bench_id = %s AND (%s::int IS NULL OR piece_id = %s)",
                      (self.bench, piece, piece))
        return [int(x) for x in str(rows).strip("[]").split(",") if x.strip()]


@asynccontextmanager
async def rig(url: str) -> AsyncGenerator[Rig]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield Rig(url, database)
    finally:
        await database.close()


def test_a_piece_keeps_its_latest_run_and_drops_the_older_ones(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.open()
            piece = await r.piece()
            first = await r.finished(piece)
            second = await r.finished(piece)
            third = await r.finished(piece)
            assert r.ids(piece) == [third]
            assert first not in r.ids() and second not in r.ids()

    run(scenario())


def test_the_latest_run_that_ran_to_its_end_is_kept_beside_a_later_one_that_did_not(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.open()
            piece = await r.piece()
            await r.finished(piece, "ran", {"old": "1"})
            kept = await r.finished(piece, "ran", {"a": "1"})
            await r.finished(piece, "timed_out")
            latest = await r.finished(piece, "failed")
            assert r.ids(piece) == [kept, latest]
            assert dict(await r.runs.files_left(r.owner.household_id, r.bench, piece)) == {"a": "1"}
            assert (await r.runs.last_on_bench(r.owner.household_id, r.bench))[piece].id == latest

    run(scenario())


def test_a_run_still_in_flight_is_never_pruned(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.open()
            piece = await r.piece()
            in_flight = await r.started(piece)
            await r.finished(piece)
            await r.finished(piece)
            assert in_flight in r.ids(piece)

    run(scenario())


def test_each_piece_keeps_its_own_and_another_bench_is_untouched(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.open()
            one, two = await r.piece(), await r.piece()
            await r.finished(one)
            await r.finished(two)
            last_one = await r.finished(one)
            assert len(r.ids(two)) == 1 and r.ids(one) == [last_one]
            first_bench, mine = r.bench, r.ids()
            await r.open()
            other = await r.piece()
            await r.finished(other)
            await r.finished(other)
            assert len(r.ids()) == 1
            r.bench = first_bench
            assert r.ids() == mine

    run(scenario())


def test_two_runs_pressed_close_together_both_keep_their_results(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.open()
            piece = await r.piece()
            first = await r.started(piece)
            second = await r.finished(piece)
            done = await r.runs.finish(first, output("ran", {"a": "1"}))
            assert done.output is not None and r.ids(piece) == [first, second]
            third = await r.finished(piece)
            assert r.ids(piece) == [third]

    run(scenario())


def test_the_count_pruned_is_logged_without_the_script(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.open()
            piece = await r.piece()
            await r.finished(piece)
            await r.finished(piece)
            await r.finished(piece)

    run(scenario())
    lines = [line for line in capsys.readouterr().out.splitlines() if "event=runs.pruned" in line]
    assert len(lines) == 2 and all("pruned=1" in line and "piece=" in line and "bench=" in line for line in lines)


def test_a_chat_turns_runs_are_all_kept(db_url: str) -> None:
    home = household(db_url)
    conversation = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    turns = [int(scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                                "VALUES (%s, %s, 'person', 't') RETURNING id", (conversation, home))) for _ in range(3)]

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            runs = PostgresRuns(database)
            for turn in turns:
                await runs.finish(await runs.start(NewRun(home, conversation, turn, f"c{turn}", "python", "s")),
                                  output("ran"))
            assert len(await runs.in_conversation(home, conversation)) == 3
        finally:
            await database.close()

    run(scenario())
