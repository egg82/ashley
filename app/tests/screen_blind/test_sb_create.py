"""Contract 1 to 5: an unlaid screen is read as its seed and nothing is written; the first command creates and seeds the
screen bench once; a device of another household, a revoked one or a command outside `ScreenCommand` changes nothing."""

import asyncio
from typing import Any

import pytest
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Archive, Rename, Run, ScreenCommand
from ashley.workshop.model import HER, By
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.screen_controls import decode
from ashley.workshop.workshop import NullWorkshop, ScreenNotFound, WorkshopUnavailable
from contract.conversations_support import TouchDatabase, run, scalar
from sb_support import (CONTROLS, CONVERSATION, HALL, PORCH, SEEDED, add, add_device, adds, benches_of, buttons_of, changed, env,
                        log_of, mv, put_rows, replayed, rows_of)

def outside() -> list[ScreenCommand]:
    """Commands a Workshop takes on a bench but not on a screen; typed loosely, since the type refuses them."""
    loose: list[Any] = [Run(HER, 1, 1, "python"), Rename(HER, "x"), Archive(HER, 1)]
    return loose


SEED = [("clock", "small"), ("home", "small"), ("controls", "medium"), ("conversation", "full")]


def test_k01_an_unlaid_screen_reads_as_its_seed_with_the_devices_rows_and_writes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            put_rows(db_url, w.tablet, w.home, PORCH, HALL)
            seen = await e.workshop.screen(w.home, w.tablet)
            assert (seen.device_id, seen.laid_out, seen.seq, seen.undo_next) == (w.tablet, False, 0, None)
            assert [(p.id, p.place.order, p.kind, p.place.size) for p in seen.pieces] == [
                (i + 1, i, k, s) for i, (k, s) in enumerate(SEED)]
            assert all(p.version == 1 and p.changed_by == p.id for p in seen.pieces)
            assert buttons_of(seen) == (PORCH, HALL)
            assert benches_of(db_url, w.tablet) == [] and rows_of(db_url, w.tablet) == 2
            assert int(scalar(db_url, "SELECT count(*) FROM bench_commands")) == 0
            assert changed(e.live) == []
            empty = await e.workshop.screen(w.home, w.kitchen)
            assert decode(next(p for p in empty.pieces if p.kind == "controls").text.body) == ()
            for p in seen.pieces:
                if p.kind != "controls":
                    assert p.text.body == ""

    run(scenario())


def test_k02_the_first_command_creates_the_bench_seeds_it_as_her_decides_as_seq_5_and_takes_the_rows(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            put_rows(db_url, w.tablet, w.home, PORCH, HALL)
            done = await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, CONVERSATION, 0, "large"))
            assert (done.seq, done.outcome) == (SEEDED + 1, "accepted")
            rows = log_of(db_url, w.tablet)
            assert [seq for seq, _, _ in rows] == [1, 2, 3, 4, 5]
            seeds = adds(rows[:SEEDED])
            assert all(c.by == HER for c in seeds) and [c.kind for c in seeds] == [k for k, _ in SEED]
            assert [c.size for c in seeds] == [s for _, s in SEED]
            assert rows[4][1].by == By(w.alana.person_id)
            assert rows_of(db_url, w.tablet) == 0
            assert len(benches_of(db_url, w.tablet)) == 1
            view = await e.workshop.screen(w.home, w.tablet)
            assert (view.laid_out, view.seq) == (True, 5) and buttons_of(view) == (PORCH, HALL)
            assert view.pieces[0].id == CONVERSATION

    run(scenario())


def test_k02_the_log_replayed_under_the_screen_rules_reproduces_the_view_and_every_outcome(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            put_rows(db_url, w.tablet, w.home, HALL)
            await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, 1, 3, "full"))
            await e.workshop.apply_screen(w.home, w.tablet, add(w.alana, "clock"))
            await e.workshop.apply_screen(w.home, w.tablet, mv(None, CONTROLS, 0, "large"))
            view = await e.workshop.screen(w.home, w.tablet)
            pieces, outcomes = replayed(db_url, w.tablet)
            assert pieces == view.pieces
            assert outcomes == [o for _, _, o in log_of(db_url, w.tablet)]
            assert outcomes[-2] == "already_shown" and view.seq == 7

    run(scenario())


def test_k03_first_applies_at_once_create_one_bench_seed_it_once_and_decide_every_command(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            for device in (w.tablet, w.kitchen):
                put_rows(db_url, device, w.home, PORCH, HALL)
            commands = [mv(w.alana, 1, 3), mv(w.sam, 2, 0, "medium"), mv(w.alana, 3, 1, "large"), mv(w.sam, 4, 2),
                        mv(w.alana, 1, 0, "full"), mv(w.sam, 3, 3)]
            for device in (w.tablet, w.kitchen):
                got = await asyncio.gather(*(e.workshop.apply_screen(w.home, device, c) for c in commands))
                assert sorted(a.seq for a in got) == list(range(SEEDED + 1, SEEDED + 1 + len(commands)))
                assert {a.outcome for a in got} == {"accepted"}
                assert len(benches_of(db_url, device)) == 1
                rows = log_of(db_url, device)
                assert [seq for seq, _, _ in rows] == list(range(1, SEEDED + len(commands) + 1))
                assert [c.kind for c in adds(rows[:SEEDED])] == [k for k, _ in SEED]
                assert rows_of(db_url, device) == 0
                assert buttons_of(await e.workshop.screen(w.home, device)) == (PORCH, HALL)
                assert replayed(db_url, device)[0] == (await e.workshop.screen(w.home, device)).pieces

    run(scenario())


def test_k04_a_device_of_another_household_a_revoked_or_unknown_one_is_not_found_and_nothing_is_logged(
        db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            for device in (w.theirs, w.revoked, 9_999_999):
                with pytest.raises(ScreenNotFound):
                    await e.workshop.screen(w.home, device)
                with pytest.raises(ScreenNotFound):
                    await e.workshop.apply_screen(w.home, device, mv(w.alana, 1, 0))
            with pytest.raises(ScreenNotFound):
                await e.workshop.apply_screen(w.next_door, w.tablet, mv(w.zed, 1, 0))
            assert int(scalar(db_url, "SELECT count(*) FROM benches")) == 0
            assert int(scalar(db_url, "SELECT count(*) FROM bench_commands")) == 0
            assert changed(e.live) == []
            await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, 1, 0))
            assert benches_of(db_url, w.tablet) != []

    run(scenario())


def test_k05_a_command_outside_screen_command_is_a_value_error_before_the_database(db_url: str) -> None:
    async def scenario() -> None:
        touched = TouchDatabase()
        workshop = PostgresWorkshop(touched, workshop_rules.load())
        for command in outside():
            with pytest.raises(ValueError):
                await workshop.apply_screen(1, 1, command)
        assert touched.touched == 0
        async with env(db_url) as e:
            w = e.world
            for command in outside():
                with pytest.raises(ValueError):
                    await e.workshop.apply_screen(w.home, w.tablet, command)
            assert benches_of(db_url, w.tablet) == [] and changed(e.live) == []

    run(scenario())


def test_k05_a_nul_in_a_text_or_a_by_outside_the_household_is_a_value_error_and_nothing_is_kept(db_url: str) -> None:
    async def scenario() -> None:
        touched = TouchDatabase()
        workshop = PostgresWorkshop(touched, workshop_rules.load())
        with pytest.raises(ValueError):
            await workshop.apply_screen(1, 1, add(None, "clock", title="a\x00b"))
        assert touched.touched == 0
        async with env(db_url) as e:
            w = e.world
            for command in (mv(w.zed, 1, 0), add(w.alana, "conversation", body="x\x00")):
                with pytest.raises(ValueError):
                    await e.workshop.apply_screen(w.home, w.tablet, command)
            assert benches_of(db_url, w.tablet) == []
            assert int(scalar(db_url, "SELECT count(*) FROM bench_commands WHERE person_id = %s", (w.zed.person_id,))) == 0
            assert changed(e.live) == []

    run(scenario())


def test_k05_the_null_workshop_raises_unavailable_for_both_screen_calls() -> None:
    async def scenario() -> None:
        for call in (lambda: NullWorkshop().screen(1, 1), lambda: NullWorkshop().apply_screen(1, 1, mv(None, 1, 0))):
            with pytest.raises(WorkshopUnavailable):
                await call()

    run(scenario())


def test_k04_a_second_unrevoked_device_added_later_has_its_own_unlaid_screen(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            w = e.world
            await e.workshop.apply_screen(w.home, w.tablet, mv(w.alana, 1, 0))
            fresh = add_device(db_url, w.home, "den tablet", "den")
            again = await e.workshop.screen(w.home, fresh)
            assert (again.laid_out, again.seq) == (False, 0)

    run(scenario())
