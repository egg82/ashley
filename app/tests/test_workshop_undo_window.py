"""Undo reaches back over a bench's last `undo_window` commands and no further: `decide` refuses an older one
`nothing_to_undo`, the walk that names the next Undo reads only that window from Postgres, and both agree on where
it starts."""

import pytest
from ashley.db.pool import PoolDatabase
from ashley.workshop import postgres_rows as rows
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Undo
from ashley.workshop.decide import Accepted, Refused, replay
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules, rules_from
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

ME = By(7)
RULES = Rules({"note": Kind("note", "stored", "Note", 10)}, max_pieces=4, title_max_chars=5, recent_commands=10,
              undo_window=3)


def add(title: str) -> Add:
    return Add(ME, "note", Text(title, ""), "small")


def test_an_undo_naming_a_command_older_than_the_window_is_nothing_to_undo() -> None:
    log = [add("a"), add("b"), add("c"), add("d")]
    refused = replay([*log, Undo(ME, 1)], RULES)[-1]
    assert isinstance(refused, Refused) and refused.reason == "nothing_to_undo" and refused.seq == 5
    assert isinstance(replay([*log, Undo(ME, 2)], RULES)[-1], Accepted)


def test_the_window_slides_with_the_log() -> None:
    log = [add("a"), add("b"), add("c"), add("d"), Undo(ME, 4), Undo(ME, 3)]
    assert all(isinstance(d, Accepted) for d in replay(log, RULES))
    after = replay([*log, Undo(ME, 2)], RULES)[-1]
    assert isinstance(after, Refused) and after.reason == "nothing_to_undo"


def test_the_window_is_data_beside_the_other_limits() -> None:
    shipped = workshop_rules.load()
    assert shipped.undo_window >= 1
    kinds = {"note": {"family": "stored", "label": "N", "max_chars": 5, "format": "plain"}}
    limits = {"max_pieces": 2, "title_max_chars": 2, "recent_commands": 2}
    with pytest.raises(ValueError):
        rules_from(kinds, limits)
    assert rules_from(kinds, {**limits, "undo_window": 9}).undo_window == 9
    with pytest.raises(ValueError):
        rules_from(kinds, {**limits, "undo_window": 0})


def test_the_read_walks_only_the_window_and_the_stored_log_agrees_with_decide(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    me = By(alana.person_id)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            shop = PostgresWorkshop(database, RULES)
            bench = await shop.open(alana, "desk")
            for title in "abcd":
                await shop.apply(alana, bench.id, Add(me, "note", Text(title, ""), "small"))
            assert (await shop.read(alana, bench.id)).undo_next == 4
            assert (await shop.apply(alana, bench.id, Undo(me, 4))).outcome == "accepted"
            assert (await shop.read(alana, bench.id)).undo_next == 3
            assert (await shop.apply(alana, bench.id, Undo(me, 3))).outcome == "accepted"
            assert (await shop.read(alana, bench.id)).undo_next is None
            assert (await shop.apply(alana, bench.id, Undo(me, 2))).outcome == "nothing_to_undo"
            assert (await shop.apply(alana, bench.id, Undo(me, 1))).outcome == "nothing_to_undo"
            async with database.connection() as conn:
                assert [s.seq for s in await rows.steps(conn, bench.id, 3)] == [6, 7, 8]
                assert len(await rows.steps(conn, bench.id, 100)) == 8
        finally:
            await database.close()

    run(scenario())
