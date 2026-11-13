"""Running a code piece (`ashley.workshop.run_piece.run_piece`) over a real database: the Run is logged, then the piece's
body run once, recorded against its command (and her turn, when she ran it); the files its last finished run left go
in with the next; a refused or impossible run runs nothing; a run is never undone and never in the way of an undo."""

from dataclasses import replace

import pytest
from bench_run_support import OK, Box, code, note, world
from ashley import logs, services
from ashley.live.events import BenchChanged, Shown
from ashley.runs.model import NewRun, Output
from ashley.runs.postgres import PostgresRuns
from ashley.runs.runs import Runs, RunsUnavailable
from ashley.workshop.commands import Edit, Run, Undo
from ashley.workshop.model import Owner, Text
from ashley.workshop.run_piece import Asked, CannotRun, run_piece
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar


class NoStart(PostgresRuns):
    async def start(self, run: NewRun) -> int:
        raise RunsUnavailable("down")


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


def by(alana: Owner, piece: int = 1, version: int = 1) -> Run:
    return Run(code(alana).by, piece, version, "python")


def test_a_run_is_logged_then_run_once_and_recorded_against_its_command(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url) as w:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            got = await run_piece(alana, bench.id, by(alana))
            assert got.applied.outcome == "accepted" and got.applied.seq == 2 and got.applied.piece_id == 1
            assert got.finished is not None and got.finished.output == OK
            assert [(j.script, dict(j.files)) for j in w.box.jobs] == [("print(1+2)", {})]
            last = (await services.get(Runs).last_on_bench(alana.household_id, bench.id))[1]
            assert last.id == got.finished.run_id and last.output == OK and last.turn_id is None
            assert last.bench is not None and (last.bench.seq, last.bench.piece_version) == (2, 1)
            log = await shop.log(alana, bench.id)
            assert (log[-1].seq, log[-1].outcome, log[-1].piece_id) == (2, "accepted", 1)
            seen = Shown(alana.household_id, alana.person_id)
            assert w.heard.events[-2:] == [BenchChanged(seen, bench.id, 2, "person")] * 2
            view = await shop.read(alana, bench.id)
            assert view.pieces[0].version == 1 and view.pieces[0].changed_by == 1

    run(scenario())


def test_the_files_the_last_finished_run_left_go_in_with_the_next(db_url: str) -> None:
    alana = owner(db_url)
    stopped = Output("timed_out", None, "", "", False, {"state.txt": "half"}, ())
    second = replace(OK, files={"state.txt": "2"})
    box = Box(outputs=[OK, stopped, second, OK])

    async def scenario() -> None:
        async with world(db_url, box) as w:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            for _ in range(4):
                await run_piece(alana, bench.id, by(alana))
            assert [dict(j.files) for j in w.box.jobs] == [{}, {"state.txt": "1"}, {"state.txt": "1"},
                                                           {"state.txt": "2"}]

    run(scenario())


def test_a_refused_run_runs_nothing(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url) as w:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, note(alana))
            await shop.apply(alana, bench.id, code(alana))
            refused = await run_piece(alana, bench.id, by(alana, 1))
            stale = await run_piece(alana, bench.id, by(alana, 2, 5))
            gone = await run_piece(alana, bench.id, by(alana, 9))
            assert (refused.applied.outcome, stale.applied.outcome, gone.applied.outcome) == (
                "not_runnable", "stale_base", "no_such_piece")
            assert refused.finished is None and stale.finished is None and w.box.jobs == []
            assert await services.get(Runs).last_on_bench(alana.household_id, bench.id) == {}

    run(scenario())


@pytest.mark.parametrize(("body", "language", "why"), [("   ", "python", "blank"), ("x" * 20001, "python", "too_long"),
                                                         ("print(1)", "cobol", "language")])
def test_a_run_the_sandbox_cannot_take_is_refused_before_anything_is_logged(db_url: str, body: str, language: str,
                                                                            why: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url) as w:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana, body))
            with pytest.raises(CannotRun) as raised:
                await run_piece(alana, bench.id, replace(by(alana), language=language))
            assert raised.value.why == why
            assert len(await shop.log(alana, bench.id)) == 1 and w.box.jobs == []

    run(scenario())


def test_her_run_is_recorded_against_her_turn_as_well(db_url: str) -> None:
    alana = owner(db_url)
    conversation = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (alana.household_id,)))
    said = int(scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                              "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conversation, alana.household_id)))

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(None))
            got = await run_piece(alana, bench.id, Run(code(None).by, 1, 1, "python"), Asked(conversation, said, "c1"))
            assert got.finished is not None
            stored = await services.get(Runs).get(alana.household_id, got.finished.run_id)
            assert stored is not None and (stored.conversation_id, stored.turn_id, stored.call_id) == (
                conversation, said, "c1")
            assert (await shop.log(alana, bench.id))[-1].by.author == "ashley"

    run(scenario())


def test_a_bench_pieces_run_is_not_served_with_the_conversation_a_chat_run_is(db_url: str) -> None:
    alana = owner(db_url)
    conversation = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'brainstorm') "
                                      "RETURNING id", (alana.household_id,)))
    said = int(scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                              "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conversation, alana.household_id)))

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(None))
            got = await run_piece(alana, bench.id, Run(code(None).by, 1, 1, "python"), Asked(conversation, said, "c1"))
            assert got.finished is not None
            runs = services.get(Runs)
            chat = await runs.start(NewRun(alana.household_id, conversation, said, "c2", "python", "print(1)"))
            assert [r.id for r in await runs.in_conversation(alana.household_id, conversation)] == [chat]

    run(scenario())


def test_a_run_is_never_undone_and_undoing_the_edit_before_it_keeps_the_run(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana, "print(1)"))
            await shop.apply(alana, bench.id, Edit(code(alana).by, 1, 1, Text("sum", "print(2)")))
            ran = await run_piece(alana, bench.id, by(alana, 1, 2))
            view = await shop.read(alana, bench.id)
            assert view.undo_next == 2
            assert (await shop.apply(alana, bench.id, Undo(code(alana).by, 3))).outcome == "nothing_to_undo"
            assert (await shop.apply(alana, bench.id, Undo(code(alana).by, 2))).outcome == "accepted"
            last = (await services.get(Runs).last_on_bench(alana.household_id, bench.id))[1]
            assert ran.finished is not None and last.id == ran.finished.run_id and last.script == "print(2)"

    run(scenario())


def test_a_run_whose_start_cannot_be_recorded_runs_nothing(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url) as w:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            services.register(Runs, NoStart(w.database))
            got = await run_piece(alana, bench.id, by(alana))
            assert got.applied.outcome == "accepted" and got.finished is None and w.box.jobs == []

    run(scenario())


def test_a_bench_of_another_household_shows_no_runs(db_url: str) -> None:
    alana, stranger = owner(db_url), owner(db_url)

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            await run_piece(alana, bench.id, by(alana))
            assert await services.get(Runs).last_on_bench(stranger.household_id, bench.id) == {}
            assert await services.get(Runs).files_left(stranger.household_id, bench.id, 1) == {}

    run(scenario())


def test_a_run_names_a_turn_whole_or_not_at_all_and_a_turn_or_a_bench() -> None:
    with pytest.raises(ValueError):
        NewRun(1, 2, None, None, "python", "s")
    with pytest.raises(ValueError):
        NewRun(1, None, None, None, "python", "s")


def test_logs_carry_the_bench_and_piece_never_the_script(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana, "print('plans-for-the-shed')"))
            await run_piece(alana, bench.id, by(alana))

    run(scenario())
    out = capsys.readouterr().out
    assert "type=run" in out and "event=runs.started" in out and "piece=1" in out
    assert "plans-for-the-shed" not in out
