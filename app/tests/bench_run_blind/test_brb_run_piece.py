"""`run_piece` over a real database: the Run command is logged, then the body runs once through the one runner,
recorded against the bench and piece, starting with the files the piece's last finished run left."""

import dataclasses
from dataclasses import dataclass

import pytest
from ashley.live.events import BenchChanged, Shown
from ashley.runs.config import load
from ashley.runs.model import Job, Outcome, Output
from ashley.workshop.commands import Add, Edit, Undo
from ashley.workshop.model import HER as HER_BY
from ashley.workshop.model import Text
from ashley.workshop.run_piece import Asked, CannotRun, run_piece
from ashley.workshop.workshop import BenchClosed, BenchNotFound
from brb_support import RAN, Box, World, add_code, add_note, by, out, run_cmd, world
from contract.conversations_support import run, scalar


async def bench_with_code(w: World, body: str = "print(1)") -> int:
    bench = await w.workshop.open(w.alana, "b")
    await w.workshop.apply(w.alana, bench.id, add_code(body, by(w.alana)))
    return bench.id


def runs_rows(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM code_runs"))


def test_a_run_is_logged_runs_the_body_once_and_is_recorded_against_the_bench_and_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w, "print('hi')")
            got = await run_piece(w.alana, bench, run_cmd(1, 1, by=by(w.alana)))
            assert got.applied.outcome == "accepted" and got.applied.seq == 2 and got.applied.piece_id == 1
            assert got.finished is not None and got.finished.output == RAN and got.finished.reached
            [job] = w.box.jobs
            assert (job.language, job.script, dict(job.files)) == ("python", "print('hi')", {})
            stored = await w.runs.get(w.alana.household_id, got.finished.run_id)
            assert stored is not None and stored.output == RAN and stored.script == "print('hi')"
            assert stored.bench is not None
            assert (stored.bench.bench_id, stored.bench.seq, stored.bench.piece_id, stored.bench.piece_version) == (
                bench, 2, 1, 1)
            assert (stored.conversation_id, stored.turn_id, stored.call_id) == (None, None, None)
            log = await w.workshop.log(w.alana, bench)
            assert [(row.seq, row.outcome) for row in log] == [(1, "accepted"), (2, "accepted")]
            assert log[1].piece_id == 1

    run(scenario())


def test_the_run_command_is_logged_and_the_run_recorded_before_the_sandbox_is_asked(db_url: str) -> None:
    seen: list[tuple[int, int]] = []

    @dataclass
    class Watching(Box):
        async def run(self, job: Job) -> Output:
            seen.append((int(scalar(db_url, "SELECT count(*) FROM bench_commands")), runs_rows(db_url)))
            return await super().run(job)

    async def scenario() -> None:
        async with world(db_url, Watching()) as w:
            bench = await bench_with_code(w)
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))

    run(scenario())
    assert seen == [(2, 1)]


def test_a_run_changes_no_piece_and_the_last_run_shows_on_the_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            before = await w.workshop.read(w.alana, bench)
            got = await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            after = await w.workshop.read(w.alana, bench)
            assert after.pieces == before.pieces and after.changes == before.changes
            assert got.finished is not None
            last = await w.runs.last_on_bench(w.alana.household_id, bench)
            assert last[1].id == got.finished.run_id

    run(scenario())


def test_the_effect_logged_is_ran_with_the_version_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            await w.workshop.apply(w.alana, bench, Edit(by(w.alana), 1, 1, Text("c", "print(2)")))
            await run_piece(w.alana, bench, run_cmd(1, 2, by=by(w.alana)))
            [job] = w.box.jobs
            assert job.script == "print(2)"
            stored = await w.runs.last_on_bench(w.alana.household_id, bench)
            assert stored[1].bench is not None and stored[1].bench.piece_version == 2

    run(scenario())


def test_the_owners_screens_are_told_again_when_the_run_has_ended(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            def told() -> int:
                return len([e for e in w.heard.events if isinstance(e, BenchChanged)])

            before = told()
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert told() >= before + 2
            shown = [e for e in w.heard.events if isinstance(e, BenchChanged)]
            assert all(e.bench_id == bench and e.shown == Shown(w.alana.household_id, w.alana.person_id) for e in shown)

    run(scenario())


# --- the files ---------------------------------------------------------------------------------------------------


def test_each_run_starts_with_the_files_the_last_finished_run_left(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", {"a": "1"}), out("ran", {"a": "2", "b": "x"}), out("ran")])) as w:
            bench = await bench_with_code(w)
            for _ in range(3):
                await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert [dict(j.files) for j in w.box.jobs] == [{}, {"a": "1"}, {"a": "2", "b": "x"}]

    run(scenario())


@pytest.mark.parametrize("outcome", ["timed_out", "out_of_memory", "failed", "unknown"])
def test_a_run_that_did_not_finish_passes_nothing_on_and_does_not_reset_the_chain(db_url: str, outcome: Outcome) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", {"keep": "1"}), out(outcome, {"half": "x"}), out("ran")])) as w:
            bench = await bench_with_code(w)
            for _ in range(3):
                await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert [dict(j.files) for j in w.box.jobs] == [{}, {"keep": "1"}, {"keep": "1"}]

    run(scenario())


def test_a_run_that_exited_non_zero_passes_its_files_on(db_url: str) -> None:
    async def scenario() -> None:
        bad = Output("ran", 2, "", "err", False, {"f": "z"}, ())
        async with world(db_url, Box([bad, out("ran")])) as w:
            bench = await bench_with_code(w)
            for _ in range(2):
                await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert [dict(j.files) for j in w.box.jobs] == [{}, {"f": "z"}]

    run(scenario())


def test_an_unreachable_sandbox_says_nothing_ran_and_passes_nothing_on(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", {"k": "v"})])) as w:
            bench = await bench_with_code(w)
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            w.box.down = True
            got = await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert got.applied.outcome == "accepted"
            assert got.finished is not None and not got.finished.reached and got.finished.output.outcome == "failed"
            w.box.down = False
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert dict(w.box.jobs[-1].files) == {"k": "v"}

    run(scenario())


def test_one_pieces_files_do_not_reach_another_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([out("ran", {"one": "1"}), out("ran")])) as w:
            bench = await bench_with_code(w)
            await w.workshop.apply(w.alana, bench, add_code("print(2)", by(w.alana)))
            await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            await run_piece(w.alana, bench, run_cmd(2, by=by(w.alana)))
            assert [dict(j.files) for j in w.box.jobs] == [{}, {}]

    run(scenario())


# --- what is refused ---------------------------------------------------------------------------------------------


def test_a_note_is_refused_not_runnable_and_logged_and_nothing_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = (await w.workshop.open(w.alana, "b")).id
            await w.workshop.apply(w.alana, bench, add_note(by(w.alana)))
            got = await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert got.applied.outcome == "not_runnable" and got.finished is None
            assert w.box.jobs == [] and runs_rows(db_url) == 0
            assert (await w.workshop.log(w.alana, bench))[-1].outcome == "not_runnable"

    run(scenario())


@pytest.mark.parametrize(("version", "piece", "outcome"), [(5, 1, "stale_base"), (1, 9, "no_such_piece")])
def test_a_stale_or_missing_piece_is_refused_logged_and_not_run(db_url: str, version: int, piece: int,
                                                                  outcome: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            got = await run_piece(w.alana, bench, run_cmd(piece, version, by=by(w.alana)))
            assert got.applied.outcome == outcome and got.finished is None and got.applied.piece_id is None
            assert w.box.jobs == [] and runs_rows(db_url) == 0
            assert (await w.workshop.log(w.alana, bench))[-1].outcome == outcome

    run(scenario())


def test_an_old_version_after_an_edit_is_stale(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            await w.workshop.apply(w.alana, bench, Edit(by(w.alana), 1, 1, Text("c", "new")))
            got = await run_piece(w.alana, bench, run_cmd(1, 1, by=by(w.alana)))
            assert got.applied.outcome == "stale_base" and w.box.jobs == []

    run(scenario())


def test_a_stale_run_of_a_piece_that_is_now_blank_is_refused_stale_not_cannot_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w, "print(1)")
            await w.workshop.apply(w.alana, bench, Edit(by(w.alana), 1, 1, Text("c", "  ")))
            got = await run_piece(w.alana, bench, run_cmd(1, 1, by=by(w.alana)))
            assert got.applied.outcome == "stale_base" and w.box.jobs == []

    run(scenario())


def test_a_blank_note_is_refused_not_runnable_not_cannot_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = (await w.workshop.open(w.alana, "b")).id
            await w.workshop.apply(w.alana, bench, Add(by(w.alana), "note", Text("n", ""), "small"))
            got = await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert got.applied.outcome == "not_runnable" and w.box.jobs == []

    run(scenario())


def refused_before_logging(db_url: str, body: str, language: str, why: str, **config: int) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w, body)
            with pytest.raises(CannotRun) as caught:
                await run_piece(w.alana, bench, run_cmd(1, language=language, by=by(w.alana)),
                                config=dataclasses.replace(load(), **config))
            assert caught.value.why == why
            assert len(await w.workshop.log(w.alana, bench)) == 1
            assert w.box.jobs == [] and runs_rows(db_url) == 0

    run(scenario())


def test_a_language_the_sandbox_does_not_run_is_refused_before_anything_is_logged(db_url: str) -> None:
    refused_before_logging(db_url, "print(1)", "cobol", "language")


def test_the_sandbox_that_offers_nothing_runs_no_language(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box(offered=())) as w:
            bench = await bench_with_code(w)
            with pytest.raises(CannotRun) as caught:
                await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert caught.value.why == "language" and len(await w.workshop.log(w.alana, bench)) == 1

    run(scenario())


@pytest.mark.parametrize("body", ["", " ", "\n\t \n"])
def test_a_blank_piece_is_refused_before_anything_is_logged(db_url: str, body: str) -> None:
    refused_before_logging(db_url, body, "python", "blank")


def test_a_piece_longer_than_the_sandbox_takes_is_too_long_and_one_exactly_as_long_is_run(db_url: str) -> None:
    refused_before_logging(db_url, "x" * 11, "python", "too_long", max_script_chars=10)

    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w, "x" * 10)
            got = await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)), config=dataclasses.replace(load(), max_script_chars=10))
            assert got.finished is not None and len(w.box.jobs) == 1

    run(scenario())


# --- whose bench -------------------------------------------------------------------------------------------------


def test_another_persons_or_households_bench_is_not_found_and_nothing_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            for stranger in (w.sam, w.zed):
                with pytest.raises(BenchNotFound):
                    await run_piece(stranger, bench, run_cmd(1, by=by(stranger)))
            assert w.box.jobs == [] and runs_rows(db_url) == 0 and len(await w.workshop.log(w.alana, bench)) == 1

    run(scenario())


def test_a_closed_bench_takes_no_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            await w.workshop.close(w.alana, bench)
            with pytest.raises(BenchClosed):
                await run_piece(w.alana, bench, run_cmd(1, by=by(w.alana)))
            assert w.box.jobs == [] and runs_rows(db_url) == 0

    run(scenario())


# --- her turn ----------------------------------------------------------------------------------------------------


def test_her_run_is_recorded_against_her_turn_as_well_as_the_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w)
            conv = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (w.alana.household_id,)))
            turn = int(scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                              "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conv, w.alana.household_id)))
            got = await run_piece(w.alana, bench, run_cmd(1, by=HER_BY), Asked(conv, turn, "call-9"))
            assert got.finished is not None
            stored = await w.runs.get(w.alana.household_id, got.finished.run_id)
            assert stored is not None and stored.bench is not None and stored.bench.piece_id == 1
            assert (stored.conversation_id, stored.turn_id, stored.call_id) == (conv, turn, "call-9")
            last = await w.runs.last_on_bench(w.alana.household_id, bench)
            assert last[1].id == stored.id
            assert (await w.workshop.log(w.alana, bench))[-1].command == run_cmd(1, by=HER_BY)

    run(scenario())


# --- undo --------------------------------------------------------------------------------------------------------


def test_undo_walks_over_runs_and_refuses_one_named_directly(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await bench_with_code(w, "a")
            me = by(w.alana)
            await w.workshop.apply(w.alana, bench, Edit(me, 1, 1, Text("c", "b")))
            ran = await run_piece(w.alana, bench, run_cmd(1, 2, by=me))
            view = await w.workshop.read(w.alana, bench)
            assert view.undo_next == 2
            named = await w.workshop.apply(w.alana, bench, Undo(me, ran.applied.seq))
            assert named.outcome == "nothing_to_undo"
            good = await w.workshop.apply(w.alana, bench, Undo(me, 2))
            assert good.outcome == "accepted"
            view = await w.workshop.read(w.alana, bench)
            [piece] = view.pieces
            assert piece.text.body == "a"
            assert view.undo_next == 1
            last = await w.runs.last_on_bench(w.alana.household_id, bench)
            assert ran.finished is not None and last[1].id == ran.finished.run_id

    run(scenario())
