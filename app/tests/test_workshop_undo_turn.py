"""A turn's commands are undone together: `undo_turn` takes back every accepted command of the turn that made the one
named, newest first, each by the ordinary undo rules, all or nothing; commands of other turns and a person's are
untouched, and the turn is logged with each of her commands."""

from dataclasses import replace

from ashley.db.pool import PoolDatabase
from ashley.workshop.codec import decode_command, encode_command
from ashley.workshop.commands import Add, Edit, Remove
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

RULES = Rules({"note": Kind("note", "stored", "Note", 100)}, max_pieces=10, title_max_chars=20, recent_commands=10,
              undo_window=50)


def hers(turn: int | None) -> By:
    return replace(HER, turn=turn)


def add(by: By, title: str) -> Add:
    return Add(by, "note", Text(title, ""), "small")


def test_a_command_is_logged_with_its_turn_and_reads_back_with_it() -> None:
    made = Remove(hers(7), 3)
    assert encode_command(made)["turn"] == 7
    assert decode_command(encode_command(made), HER) == made
    assert "turn" not in encode_command(Remove(HER, 3))


def test_a_turns_commands_are_undone_together_and_other_turns_are_left(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            shop = PostgresWorkshop(database, RULES)
            bench = (await shop.open(alana, "desk")).id
            mine = By(alana.person_id)
            await shop.apply(alana, bench, add(mine, "person's"))
            await shop.apply(alana, bench, add(hers(5), "a"))
            await shop.apply(alana, bench, add(hers(5), "b"))
            await shop.apply(alana, bench, Edit(hers(5), 2, 1, Text("a2", "")))
            await shop.apply(alana, bench, add(hers(6), "other turn"))
            done = await shop.undo_turn(alana, bench, hers(9), 3)
            assert done.undone == (4, 3, 2) and done.refused == ()
            view = await shop.read(alana, bench)
            assert [p.text.title for p in view.pieces] == ["person's", "other turn"]
            again = await shop.undo_turn(alana, bench, hers(9), 3)
            assert again.undone == () and again.refused == ((3, "nothing_to_undo"),)
        finally:
            await database.close()

    run(scenario())


def test_one_command_changed_since_refuses_the_group_and_nothing_is_undone(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            shop = PostgresWorkshop(database, RULES)
            bench = (await shop.open(alana, "desk")).id
            await shop.apply(alana, bench, add(hers(5), "a"))
            await shop.apply(alana, bench, add(hers(5), "b"))
            await shop.apply(alana, bench, Edit(By(alana.person_id), 1, 1, Text("a by hand", "")))
            before = await shop.read(alana, bench)
            done = await shop.undo_turn(alana, bench, hers(9), 2)
            assert done.undone == () and done.refused == ((1, "changed_since"),)
            after = await shop.read(alana, bench)
            assert after.pieces == before.pieces and after.undo_next == before.undo_next
            assert len(await shop.log(alana, bench)) == 3
        finally:
            await database.close()

    run(scenario())


def test_a_command_made_in_no_turn_has_no_group(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        try:
            shop = PostgresWorkshop(database, RULES)
            bench = (await shop.open(alana, "desk")).id
            await shop.apply(alana, bench, add(HER, "a"))
            done = await shop.undo_turn(alana, bench, hers(9), 1)
            assert done.refused == ((1, "nothing_to_undo"),) and len((await shop.read(alana, bench)).pieces) == 1
        finally:
            await database.close()

    run(scenario())
