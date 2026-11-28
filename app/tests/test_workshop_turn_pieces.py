"""`Workshop.turn_pieces`: the pieces each turn touched, read from the command log by `By.turn`: accepted commands only,
both ends of a link, an undone command still counted, one bench and one owner at a time."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from ashley.db.pool import PoolDatabase
from ashley.workshop.commands import Add, Edit, Link, Remove, Undo, Unlink
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import BenchNotFound, Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

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


def hers(turn: int | None) -> By:
    return replace(HER, turn=turn)


def add(title: str, by: By = HER) -> Add:
    return Add(by, "note", Text(title, ""), "small")


def test_each_turn_has_the_sorted_pieces_its_accepted_commands_touched(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            for c in (add("a", hers(5)), add("b", hers(5)), add("c", hers(6)), add("d", By(alana.person_id)),
                      Edit(hers(6), 1, 1, Text("a2", "")), Edit(hers(7), 99, 1, Text("x", ""))):
                await shop.apply(alana, bench, c)
            got = await shop.turn_pieces(alana, bench, frozenset({5, 6, 7, 8}))
            assert got == {5: (1, 2), 6: (1, 3)}
            assert await shop.turn_pieces(alana, bench, frozenset({6})) == {6: (1, 3)}
            assert await shop.turn_pieces(alana, bench, frozenset()) == {}

    run(scenario())


def test_a_link_counts_for_both_ends_and_an_undone_command_still_counts(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            for c in (add("a"), add("b"), add("c"), Link(hers(5), 3, "part_of", 1), Unlink(hers(6), 2, "depends_on", 1)):
                await shop.apply(alana, bench, c)
            assert await shop.turn_pieces(alana, bench, frozenset({5, 6})) == {5: (1, 3)}
            await shop.apply(alana, bench, Add(hers(7), "note", Text("d", ""), "small"))
            await shop.apply(alana, bench, Remove(hers(8), 2))
            await shop.apply(alana, bench, Undo(By(alana.person_id), 7))  # takes back the Remove
            assert await shop.turn_pieces(alana, bench, frozenset({7, 8})) == {7: (6,), 8: (2,)}

    run(scenario())


def test_a_refused_command_touches_nothing(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            await shop.apply(alana, bench, add("a"))
            refused = await shop.apply(alana, bench, Link(hers(5), 1, "part_of", 9))
            assert refused.outcome != "accepted"
            assert await shop.turn_pieces(alana, bench, frozenset({5})) == {}

    run(scenario())


def test_another_bench_and_another_owner_are_never_read(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    other = Owner(household(db_url), 0)
    other = Owner(other.household_id, person(db_url, other.household_id))

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            one = (await shop.open(alana, "one")).id
            two = (await shop.open(alana, "two")).id
            theirs = (await shop.open(other, "theirs")).id
            await shop.apply(alana, one, add("a", hers(5)))
            await shop.apply(alana, two, add("b", hers(5)))
            await shop.apply(alana, two, add("c", hers(5)))
            await shop.apply(other, theirs, add("z", hers(5)))
            assert await shop.turn_pieces(alana, one, frozenset({5})) == {5: (1,)}
            assert await shop.turn_pieces(alana, two, frozenset({5})) == {5: (1, 2)}
            with pytest.raises(BenchNotFound):
                await shop.turn_pieces(alana, theirs, frozenset({5}))
            with pytest.raises(BenchNotFound):
                await shop.turn_pieces(other, one, frozenset({5}))

    run(scenario())
