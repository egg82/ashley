"""A device's screen as a bench of the device's: laid out on its first command, seeded from the shipped seed with the
device's own buttons, logged and undone as a bench is, and never visible as a person's bench."""

import asyncio
from typing import Any

import psycopg
import pytest
from ashley.db.pool import PoolDatabase
from ashley.live.events import ScreenChanged, Shown
from ashley.workshop import screen_controls
from ashley.workshop import postgres_rows as rows
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Archive, Edit, Move, Remove, Rename, Run, Undo
from ashley.workshop.decide import Accepted, Refused, replay
from ashley.workshop.model import HER, By, Place, Text
from ashley.workshop.workshop import ScreenNotFound
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template, run
from screen_bench_support import LIGHT, SCENE, count, device, household, legacy_controls, person, shop

SEED_KINDS = ["clock", "home", "controls", "conversation"]


def loose(value: object) -> Any:
    return value


def test_an_unlaid_screen_is_the_seed_with_the_devices_buttons_and_writes_nothing(db_url: str) -> None:
    home = household(db_url)
    tablet = device(db_url, home)
    legacy_controls(db_url, home, tablet, LIGHT, SCENE)

    async def scenario() -> None:
        async with shop(db_url) as (workshop, _):
            view = await workshop.screen(home, tablet)
            assert (view.laid_out, view.seq, view.undo_next) == (False, 0, None)
            assert [p.kind for p in view.pieces] == SEED_KINDS
            assert [p.id for p in view.pieces] == [1, 2, 3, 4] and [p.place.order for p in view.pieces] == [0, 1, 2, 3]
            assert [c.id for c in screen_controls.decode(view.pieces[2].text.body)] == ["bedroom-off", "nightlight"]
            assert count(db_url, "SELECT count(*) FROM benches WHERE device_id IS NOT NULL") == 0
            assert count(db_url, "SELECT count(*) FROM device_controls") == 2

    run(scenario())


def test_the_first_command_lays_the_screen_out_moves_the_buttons_and_replays_to_the_view(db_url: str) -> None:
    home = household(db_url)
    tablet = device(db_url, home)
    legacy_controls(db_url, home, tablet, LIGHT)

    async def scenario() -> None:
        async with shop(db_url) as (workshop, live):
            applied = await workshop.apply_screen(home, tablet, Move(HER, 4, Place(0, "large")))
            assert applied.outcome == "accepted" and applied.seq == 5
            assert count(db_url, "SELECT count(*) FROM device_controls") == 0
            assert count(db_url, "SELECT count(*) FROM bench_commands c JOIN benches b ON b.id = c.bench_id "
                                 "WHERE b.device_id = %s AND c.person_id IS NULL AND c.seq <= 4", tablet) == 4
            view = await workshop.screen(home, tablet)
            assert view.laid_out and view.seq == 5 and view.undo_next == 5
            assert [p.kind for p in view.pieces] == ["conversation", *SEED_KINDS[:3]]
            assert [d for d in live.published] == [ScreenChanged(Shown(home, None), tablet, 5)]
            assert [c.id for c in screen_controls.decode(view.pieces[3].text.body)] == ["bedroom-off"]

    run(scenario())


def test_two_first_commands_at_once_make_one_bench_and_decide_both(db_url: str) -> None:
    home = household(db_url)
    tablet = device(db_url, home)

    async def scenario() -> None:
        async with shop(db_url) as (workshop, _):
            both = await asyncio.gather(workshop.apply_screen(home, tablet, Move(HER, 1, Place(3, "small"))),
                                        workshop.apply_screen(home, tablet, Move(HER, 2, Place(3, "small"))))
            assert sorted(a.seq for a in both) == [5, 6] and all(a.outcome == "accepted" for a in both)
            assert count(db_url, "SELECT count(*) FROM benches WHERE device_id = %s", tablet) == 1
            assert count(db_url, "SELECT count(*) FROM bench_commands c JOIN benches b ON b.id = c.bench_id "
                                 "WHERE b.device_id = %s AND c.seq <= 4 AND c.command->>'type' = 'add'", tablet) == 4

    run(scenario())


def test_another_household_or_a_revoked_device_has_no_screen_and_nothing_is_logged(db_url: str) -> None:
    home, other = household(db_url), household(db_url, "other")
    tablet = device(db_url, home)
    gone = device(db_url, home, "gone")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE devices SET revoked_at = now() WHERE id = %s", (gone,))

    async def scenario() -> None:
        async with shop(db_url) as (workshop, live):
            for who, which in ((other, tablet), (home, gone), (home, 999)):
                with pytest.raises(ScreenNotFound):
                    await workshop.screen(who, which)
                with pytest.raises(ScreenNotFound):
                    await workshop.apply_screen(who, which, Move(HER, 1, Place(0, "small")))
            assert count(db_url, "SELECT count(*) FROM benches WHERE device_id IS NOT NULL") == 0 and not live.published

    run(scenario())


def test_what_a_screen_does_not_take_raises_before_the_database(db_url: str) -> None:
    home = household(db_url)
    tablet = device(db_url, home)
    stranger = person(db_url, household(db_url, "elsewhere"))

    async def scenario() -> None:
        async with shop(db_url) as (workshop, _):
            for command in (Run(HER, 1, 1, "python"), Rename(HER, "x"), Archive(HER, 1)):
                with pytest.raises(ValueError):
                    await workshop.apply_screen(home, tablet, loose(command))
            with pytest.raises(ValueError):
                await workshop.apply_screen(home, tablet, Edit(HER, 3, 1, Text("a\x00", "[]")))
            with pytest.raises(ValueError):
                await workshop.apply_screen(home, tablet, Move(By(stranger), 1, Place(0, "small")))
            assert count(db_url, "SELECT count(*) FROM benches WHERE device_id IS NOT NULL") == 0

    run(scenario())


def test_an_accepted_command_announces_once_a_refusal_on_an_existing_screen_says_nothing_and_a_creating_refusal_still_does(
        db_url: str) -> None:
    home = household(db_url)
    tablet, other = device(db_url, home), device(db_url, home, "other")

    async def scenario() -> None:
        async with shop(db_url) as (workshop, live):
            refused = await workshop.apply_screen(home, tablet, Remove(HER, 4))
            assert refused.outcome == "required" and refused.seq == 5
            assert live.published == [ScreenChanged(Shown(home, None), tablet, 5)]
            again = await workshop.apply_screen(home, tablet, Remove(HER, 4))
            assert again.outcome == "required" and len(live.published) == 1
            done = await workshop.apply_screen(home, tablet, Remove(HER, 1))
            assert done.outcome == "accepted" and live.published[-1] == ScreenChanged(Shown(home, None), tablet, 7)
            assert len(live.published) == 2
            await workshop.apply_screen(home, other, Move(HER, 1, Place(1, "large")))
            assert [e.device_id for e in live.published if isinstance(e, ScreenChanged)] == [tablet, tablet, other]

    run(scenario())


def test_the_screen_log_replayed_under_the_screen_rules_is_the_view(db_url: str) -> None:
    home = household(db_url)
    tablet = device(db_url, home)

    async def scenario() -> None:
        async with shop(db_url) as (workshop, _):
            for command in (Move(HER, 4, Place(0, "large")), Remove(HER, 2), Move(HER, 1, Place(5, "small")), Undo(HER, 6)):
                await workshop.apply_screen(home, tablet, command)
            view = await workshop.screen(home, tablet)
        database = PoolDatabase(db_url)
        await database.open()
        try:
            async with database.connection() as conn:
                found = await rows.logged(conn, count(db_url, "SELECT id FROM benches WHERE device_id = %s", tablet))
        finally:
            await database.close()
        assert [entry.outcome for entry in found][4:] == ["accepted", "accepted", "bad_place", "accepted"]
        replayed = replay([entry.command for entry in found], workshop_rules.load_screen(), "Screen")
        assert [d.reason if isinstance(d, Refused) else "accepted" for d in replayed][4:] == [
            "accepted", "accepted", "bad_place", "accepted"]
        last = replayed[-1]
        assert isinstance(last, Accepted) and last.state.pieces == view.pieces and view.seq == 8

    run(scenario())
