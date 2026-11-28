"""Links over a real database: written with their command, read back only while both ends are on the layout, kept
through a remove or an archive so the undo or restore brings them back, replayed from the stored log, undone with
their turn, and refused like any other command."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace

from ashley.db.pool import PoolDatabase
from ashley.workshop.commands import Add, Archive, Command, Link, Remove, Restore, Undo, Unlink
from ashley.workshop.decide import replay
from ashley.workshop.links import PieceLink, visible
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar

RULES = Rules({"note": Kind("note", "stored", "Note", 20)}, max_pieces=6, title_max_chars=12, recent_commands=5,
              undo_window=100, link_kinds={"part_of": "Part of", "depends_on": "Depends on"})


@asynccontextmanager
async def workshop_on(url: str) -> AsyncGenerator[Workshop]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresWorkshop(database, RULES)
    finally:
        await database.close()


def owner_in(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


def add(title: str, by: By = HER) -> Add:
    return Add(by, "note", Text(title, ""), "small")


def test_a_link_is_stored_with_its_command_and_read_while_both_ends_are_on_the_layout(db_url: str) -> None:
    alana = owner_in(db_url)
    me = By(alana.person_id)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            for c in (add("plan"), add("step"), add("tool"), Link(me, 2, "part_of", 1), Link(HER, 3, "depends_on", 2)):
                assert (await shop.apply(alana, bench, c)).outcome == "accepted"
            assert scalar(db_url, "SELECT count(*) FROM bench_links WHERE bench_id = %s AND household_id = %s",
                          (bench, alana.household_id)) == 2
            assert scalar(db_url, "SELECT seq FROM bench_links WHERE bench_id = %s AND from_piece = 2", (bench,)) == 4
            view = await shop.read(alana, bench)
            assert view.links == (PieceLink(2, "part_of", 1), PieceLink(3, "depends_on", 2))
            assert [p.changed_by for p in view.pieces] == [1, 2, 3] and [p.version for p in view.pieces] == [1, 1, 1]
            applied = await shop.apply(alana, bench, Link(me, 2, "part_of", 1))
            assert (applied.outcome, applied.piece_id) == ("already_linked", None)
            assert (await shop.apply(alana, bench, Unlink(me, 3, "depends_on", 2))).piece_id == 3
            assert (await shop.read(alana, bench)).links == (PieceLink(2, "part_of", 1),)

    run(scenario())


def test_removing_or_shelving_an_end_keeps_the_row_and_its_undo_or_restore_shows_it_again(db_url: str) -> None:
    alana = owner_in(db_url)
    me = By(alana.person_id)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            for c in (add("plan"), add("step"), add("tool"), Link(me, 2, "part_of", 1), Link(me, 3, "depends_on", 1)):
                await shop.apply(alana, bench, c)
            await shop.apply(alana, bench, Remove(me, 2))
            await shop.apply(alana, bench, Archive(me, 3))
            assert (await shop.read(alana, bench)).links == ()
            assert scalar(db_url, "SELECT count(*) FROM bench_links WHERE bench_id = %s", (bench,)) == 2
            assert (await shop.apply(alana, bench, Link(me, 1, "part_of", 2))).outcome == "no_such_piece"
            assert (await shop.apply(alana, bench, Undo(me, 6))).outcome == "accepted"
            assert (await shop.read(alana, bench)).links == (PieceLink(2, "part_of", 1),)
            assert (await shop.apply(alana, bench, Restore(me, 3))).outcome == "accepted"
            assert (await shop.read(alana, bench)).links == (PieceLink(2, "part_of", 1), PieceLink(3, "depends_on", 1))

    run(scenario())


def test_undo_takes_a_link_back_and_an_unlink_back_through_the_ordinary_rules(db_url: str) -> None:
    alana = owner_in(db_url)
    me = By(alana.person_id)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            for c in (add("plan"), add("step"), Link(me, 2, "part_of", 1), Unlink(HER, 2, "part_of", 1)):
                await shop.apply(alana, bench, c)
            assert (await shop.read(alana, bench)).undo_next == 4
            assert (await shop.apply(alana, bench, Undo(me, 3))).outcome == "changed_since"
            assert (await shop.apply(alana, bench, Undo(me, 4))).outcome == "accepted"
            assert (await shop.read(alana, bench)).links == (PieceLink(2, "part_of", 1),)
            assert (await shop.read(alana, bench)).undo_next == 3
            assert (await shop.apply(alana, bench, Undo(me, 3))).outcome == "accepted"
            assert (await shop.read(alana, bench)).links == ()
            assert scalar(db_url, "SELECT count(*) FROM bench_links WHERE bench_id = %s", (bench,)) == 0

    run(scenario())


def test_the_stored_log_replays_to_the_links_read_shows(db_url: str) -> None:
    alana = owner_in(db_url)
    me = By(alana.person_id)
    commands: list[Command] = [
        add("a"), add("b"), add("c"), Link(me, 2, "part_of", 1), Link(HER, 3, "part_of", 1), Link(me, 3, "part_of", 3),
        Remove(me, 1), Undo(me, 5), Link(me, 2, "depends_on", 3), Undo(me, 7), Unlink(me, 9, "part_of", 1),
        Archive(me, 3), Link(me, 1, "depends_on", 2)]

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            applied = [await shop.apply(alana, bench, c) for c in commands]
            log = await shop.log(alana, bench)
            view = await shop.read(alana, bench)
            final = replay([row.command for row in log], RULES, "desk")[-1].state
            assert [row.outcome for row in log] == [a.outcome for a in applied]
            assert view.links == visible(final.links, final.pieces)
            assert view.links == (PieceLink(1, "depends_on", 2), PieceLink(2, "part_of", 1))
            stored = scalar(db_url, "SELECT count(*) FROM bench_links WHERE bench_id = %s", (bench,))
            assert stored == len(final.links)

    run(scenario())


def test_a_turns_links_are_undone_with_its_pieces(db_url: str) -> None:
    alana = owner_in(db_url)
    turn = replace(HER, turn=5)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            await shop.apply(alana, bench, add("person's", By(alana.person_id)))
            await shop.apply(alana, bench, add("step", turn))
            await shop.apply(alana, bench, Link(turn, 2, "part_of", 1))
            await shop.apply(alana, bench, Link(replace(HER, turn=6), 1, "depends_on", 2))
            done = await shop.undo_turn(alana, bench, replace(HER, turn=9), 2)
            assert done.undone == (3, 2) and done.refused == ()
            view = await shop.read(alana, bench)
            assert [p.text.title for p in view.pieces] == ["person's"] and view.links == ()
            assert scalar(db_url, "SELECT count(*) FROM bench_links WHERE bench_id = %s AND kind = 'part_of'",
                          (bench,)) == 0

    run(scenario())
