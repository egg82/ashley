"""The bench read's `undo_next` walks only the last `undo_window` commands, so it never offers an Undo that `decide`
refuses for being outside the window; `steps` is the bounded read of the log it walks."""

import psycopg
from ashley.workshop import postgres_rows
from ashley.workshop.undo_walk import Step
from contract.conversations_support import run
from ll_support import HER, World, add, bad, run_cmd, undo, world


async def pressed(w: World, bench: int) -> list[int]:
    """Press Undo as the screen does until nothing is offered; every press must be accepted."""
    taken: list[int] = []
    for _ in range(30):
        view = await w.workshop.read(w.alana, bench)
        if view.undo_next is None:
            return taken
        applied = await w.workshop.apply(w.alana, bench, undo(view.undo_next, HER))
        assert applied.outcome == "accepted", f"offered {view.undo_next}, refused {applied.outcome}"
        taken.append(view.undo_next)
    raise AssertionError("the walk never ended")


def test_the_walk_stops_where_the_window_ends_and_never_offers_a_refused_undo(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, window=3) as w:
            bench = (await w.workshop.open(w.alana, "b")).id
            for _ in range(5):
                await w.workshop.apply(w.alana, bench, add(by=HER))
            assert (await w.workshop.read(w.alana, bench)).undo_next == 5
            assert await pressed(w, bench) == [5, 4]
            view = await w.workshop.read(w.alana, bench)
            assert view.undo_next is None and len(view.pieces) == 3

    run(scenario())


def test_an_undo_older_than_the_window_is_refused_by_the_service(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, window=3) as w:
            bench = (await w.workshop.open(w.alana, "b")).id
            for _ in range(5):
                await w.workshop.apply(w.alana, bench, add(by=HER))
            assert (await w.workshop.apply(w.alana, bench, undo(3, HER))).outcome == "accepted"
            assert (await w.workshop.apply(w.alana, bench, undo(2, HER))).outcome == "nothing_to_undo"

    run(scenario())


def test_refusals_and_runs_push_the_walk_out_of_reach(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, window=3) as w:
            bench = (await w.workshop.open(w.alana, "b")).id
            await w.workshop.apply(w.alana, bench, add("code", HER))
            await w.workshop.apply(w.alana, bench, add(by=HER))
            assert (await w.workshop.read(w.alana, bench)).undo_next == 2
            for _ in range(2):
                assert (await w.workshop.apply(w.alana, bench, bad(HER))).outcome != "accepted"
            assert (await w.workshop.read(w.alana, bench)).undo_next == 2
            assert (await w.workshop.apply(w.alana, bench, bad(HER))).outcome != "accepted"
            assert (await w.workshop.read(w.alana, bench)).undo_next is None
            other = (await w.workshop.open(w.alana, "c")).id
            await w.workshop.apply(w.alana, other, add("code", HER))
            await w.workshop.apply(w.alana, other, add(by=HER))
            for _ in range(3):
                assert (await w.workshop.apply(w.alana, other, run_cmd(1, HER))).outcome == "accepted"
            assert (await w.workshop.read(w.alana, other)).undo_next is None

    run(scenario())


def test_steps_are_the_newest_commands_oldest_first_with_what_the_walk_needs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = (await w.workshop.open(w.alana, "b")).id
            other = (await w.workshop.open(w.alana, "o")).id
            await w.workshop.apply(w.alana, other, add(by=HER))
            for command in (add("code", HER), add(by=HER), bad(HER), undo(2, HER), run_cmd(1, HER)):
                await w.workshop.apply(w.alana, bench, command)
            async with await psycopg.AsyncConnection.connect(db_url) as conn:
                assert await postgres_rows.steps(conn, bench, 3) == [Step(3, False), Step(4, True, 2), Step(5, True, None, True)]
                every = await postgres_rows.steps(conn, bench, 50)
                assert [s.seq for s in every] == [1, 2, 3, 4, 5]
                assert await postgres_rows.steps(conn, bench, 1) == [Step(5, True, None, True)]

    run(scenario())
