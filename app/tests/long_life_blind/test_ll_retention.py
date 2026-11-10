"""Code-run retention from the contract alone: finishing a bench piece's run deletes that piece's older finished runs,
keeping the highest-id run, the highest-id run that ran to its end and the run being finished; a run still in flight,
a chat turn's run and every other piece's, bench's and household's runs are untouched; the files the next run
receives are unchanged by pruning."""

import random

import psycopg
import pytest
from ashley import logs
from ashley.runs.model import NewRun, Outcome, Output
from contract.conversations_support import events, run
from ll_support import RAN, World, alive, bench_with_codes, done, out, start, world


def chat_run(w: World, url: str) -> NewRun:
    with psycopg.connect(url) as conn:
        conv = conn.execute("INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                            (w.alana.household_id,)).fetchone()
        assert conv is not None
        turn = conn.execute("INSERT INTO turns (conversation_id, household_id, author, text) VALUES (%s, %s, 'person', 'x') "
                            "RETURNING id", (conv[0], w.alana.household_id)).fetchone()
        assert turn is not None
    return NewRun(w.alana.household_id, conv[0], turn[0], "c", "python", "s", "", {"a": "b"})


def test_finished_runs_that_ran_leave_only_the_newest(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            ids = [await done(w, bench, 1, out("ran", {"f": str(i)})) for i in range(4)]
            assert await alive(w, ids) == [ids[-1]]

    run(scenario())


def test_the_newest_run_that_ran_survives_later_runs_that_did_not(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            first = await done(w, bench, 1, out("ran", {"f": "1"}))
            second = await done(w, bench, 1, out("ran", {"f": "2"}))
            lost = [await done(w, bench, 1, out("timed_out")) for _ in range(3)]
            assert await alive(w, [first, second, *lost]) == [second, lost[-1]]
            assert dict(await w.runs.files_left(w.alana.household_id, bench, 1)) == {"f": "2"}

    run(scenario())


@pytest.mark.parametrize("outcome", ["timed_out", "out_of_memory", "failed", "unknown"])
def test_a_run_that_ran_is_kept_under_any_number_of_runs_that_did_not(db_url: str, outcome: Outcome) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            kept = await done(w, bench, 1, out("ran", {"keep": "me"}))
            others = [await done(w, bench, 1, out(outcome, {"half": "x"})) for _ in range(3)]
            assert await alive(w, [kept, *others]) == [kept, others[-1]]
            assert dict(await w.runs.files_left(w.alana.household_id, bench, 1)) == {"keep": "me"}

    run(scenario())


def test_a_run_that_ran_non_zero_counts_as_having_run_to_its_end(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            failed_exit = await done(w, bench, 1, Output("ran", 3, "", "boom", False, {"x": "y"}, ()))
            lost = [await done(w, bench, 1, out("failed")) for _ in range(2)]
            assert await alive(w, [failed_exit, *lost]) == [failed_exit, lost[-1]]

    run(scenario())


def test_a_run_in_flight_is_never_deleted(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            flying = await start(w, bench, 1)
            finished = [await done(w, bench, 1, out("ran")) for _ in range(3)]
            assert await alive(w, [flying, *finished]) == [flying, finished[-1]]
            await w.runs.finish(flying, RAN)
            assert await alive(w, [flying, *finished]) == [flying, finished[-1]]

    run(scenario())


def test_finishing_an_older_run_keeps_the_newer_ones_and_itself(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            old = await start(w, bench, 1)
            new = await start(w, bench, 1)
            await w.runs.finish(new, out("ran", {"n": "1"}))
            await w.runs.finish(old, out("timed_out"))
            assert await alive(w, [old, new]) == [old, new]

    run(scenario())


def test_other_pieces_benches_and_households_are_untouched(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            elsewhere = await bench_with_codes(w)
            theirs = await bench_with_codes(w, w.zed, pieces=1)
            piece2 = [await done(w, bench, 2) for _ in range(2)]
            other_bench = [await done(w, elsewhere, 1) for _ in range(2)]
            zed = [await done(w, theirs, 1, owner=w.zed) for _ in range(2)]
            mine = [await done(w, bench, 1) for _ in range(3)]
            assert await alive(w, mine) == [mine[-1]]
            assert await alive(w, piece2) == [piece2[-1]], "piece 2 was pruned only by its own finishes"
            assert await alive(w, other_bench) == [other_bench[-1]]
            assert await alive(w, zed, w.zed) == [zed[-1]]

    run(scenario())


def test_a_finish_prunes_nothing_of_the_other_pieces_older_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            first = await start(w, bench, 2)
            second = await start(w, bench, 2)
            await w.runs.finish(first, RAN)
            await w.runs.finish(second, RAN)
            assert await alive(w, [first, second]) == [second]
            older = await start(w, bench, 2)
            newer = await start(w, bench, 2)
            await w.runs.finish(older, RAN)
            await done(w, bench, 1)
            await done(w, bench, 1)
            assert await alive(w, [older, newer]) == [older, newer], "pieces 1's finishes left piece 2's runs alone"

    run(scenario())


def test_a_chat_turns_runs_are_never_deleted_and_protect_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            chat: list[int] = []
            before = await w.runs.start(chat_run(w, db_url))
            await w.runs.finish(before, RAN)
            chat.append(before)
            first = await done(w, bench, 1)
            second = await done(w, bench, 1)
            after = await w.runs.start(chat_run(w, db_url))
            await w.runs.finish(after, RAN)
            chat.append(after)
            third = await done(w, bench, 1)
            assert await alive(w, chat) == chat
            assert await alive(w, [first, second, third]) == [third]

    run(scenario())


def test_the_files_the_next_run_gets_are_those_of_the_last_run_that_ran_at_every_step(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w, pieces=1)
            expected: dict[str, str] = {}
            plan: list[Outcome] = ["ran", "failed", "ran", "timed_out", "timed_out", "out_of_memory", "ran", "unknown"]
            for i, outcome in enumerate(plan):
                files = {f"f{i}": str(i)}
                await done(w, bench, 1, out(outcome, files))
                if outcome == "ran":
                    expected = files
                assert dict(await w.runs.files_left(w.alana.household_id, bench, 1)) == expected

    run(scenario())


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_survivors_match_the_stated_rule_over_random_interleavings(db_url: str, seed: int) -> None:
    """A model of the rule: after each finish, a piece keeps its unfinished runs, its highest id, its highest id that
    ran and the run just finished; everything else finished is gone."""
    async def scenario() -> None:
        rng = random.Random(seed)
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            runs: dict[int, tuple[int, Outcome | None]] = {}
            gone: set[int] = set()
            for _ in range(14):
                flying = [i for i, (_, o) in runs.items() if o is None]
                if flying and rng.random() < 0.5:
                    rid = rng.choice(flying)
                else:
                    piece = rng.choice((1, 2))
                    rid = await start(w, bench, piece)
                    runs[rid] = (piece, None)
                    if rng.random() < 0.4:
                        continue
                outcome: Outcome = rng.choice(("ran", "ran", "failed", "timed_out"))
                await w.runs.finish(rid, out(outcome))
                piece = runs[rid][0]
                runs[rid] = (piece, outcome)
                mine = {i: o for i, (p, o) in runs.items() if p == piece and i not in gone}
                keep = {rid, max(mine), *[i for i, o in mine.items() if o is None]}
                ran = [i for i, o in mine.items() if o == "ran"]
                if ran:
                    keep.add(max(ran))
                gone |= set(mine) - keep
                assert set(await alive(w, list(runs))) == set(runs) - gone

    run(scenario())


def test_pruning_is_logged_with_its_count_only_when_something_went(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def scenario() -> None:
        async with world(db_url) as w:
            await bench_with_codes(w)
            await bench_with_codes(w)
            bench = await bench_with_codes(w)
            assert bench == 3
            await done(w, bench, 2)
            assert events(capsys.readouterr().out, "runs.pruned") == []
            await done(w, bench, 2)
            first = events(capsys.readouterr().out, "runs.pruned")
            assert [(e["bench"], e["piece"], e["pruned"]) for e in first] == [("3", "2", "1")]
            for _ in range(2):
                await start(w, bench, 2)
            await done(w, bench, 2)
            await done(w, bench, 2)
            seen = events(capsys.readouterr().out, "runs.pruned")
            assert [e["pruned"] for e in seen] == ["1", "1"]

    run(scenario())


def test_one_finish_can_prune_several_runs_and_logs_how_many(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()

    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            ids = [await start(w, bench, 1) for _ in range(5)]
            plan: list[tuple[int, Outcome]] = [(4, "failed"), (0, "ran"), (1, "failed")]
            for index, outcome in plan:
                await w.runs.finish(ids[index], out(outcome))
            capsys.readouterr()
            await w.runs.finish(ids[2], out("ran"))
            assert await alive(w, ids) == [ids[2], ids[3], ids[4]]
            assert [e["pruned"] for e in events(capsys.readouterr().out, "runs.pruned")] == ["2"]

    run(scenario())


def test_the_highest_id_run_is_kept_when_it_is_neither_the_one_finishing_nor_one_that_ran(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_codes(w)
            low = await start(w, bench, 1)
            high = await start(w, bench, 1)
            await w.runs.finish(high, out("timed_out"))
            await w.runs.finish(low, out("ran", {"f": "1"}))
            assert await alive(w, [low, high]) == [low, high]

    run(scenario())
