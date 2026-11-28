"""Pins and boxes over a real database: a person's move writes them to the piece's row and a read returns them, a move
that leaves them out keeps them, an undo puts back the exact ones replaced, the stored log replays to what a read
shows, and a log row written before pins replays as it did."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from psycopg.types.json import Jsonb

from ashley.db.pool import PoolDatabase
from ashley.workshop.commands import Add, Command, Move, Undo
from ashley.workshop.decide import replay
from ashley.workshop.model import HER, Box, By, Owner, Pin, Place, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Layout, Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import aexecute, household, person, run, scalar

RULES = Rules({"note": Kind("note", "stored", "Note", 20)}, max_pieces=6, title_max_chars=12, recent_commands=5,
              undo_window=100, layout=Layout(pin_reach=5000, min_w=100, max_w=2000, min_h=50, max_h=2000))
PIN, BOX = Pin(-300, 40), Box(420, 260)


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


def test_a_pin_and_box_are_stored_kept_by_her_move_and_put_back_by_undo(db_url: str) -> None:
    alana = owner_in(db_url)
    me = By(alana.person_id)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            for c in (add("plan"), add("step"), Move(me, 1, Place(0, "small"), PIN, BOX)):
                assert (await shop.apply(alana, bench, c)).outcome == "accepted"
            assert scalar(db_url, "SELECT array[pin_x, pin_y, box_w, box_h] FROM bench_pieces WHERE bench_id = %s "
                          "AND piece_id = 1", (bench,)) == [-300, 40, 420, 260]
            assert (await shop.read(alana, bench)).pieces[0].place == Place(0, "small", PIN, BOX)
            assert (await shop.apply(alana, bench, Move(HER, 1, Place(1, "large")))).outcome == "accepted"
            assert (await shop.read(alana, bench)).pieces[1].place == Place(1, "large", PIN, BOX)
            assert (await shop.apply(alana, bench, Move(me, 1, Place(1, "large"), None, None))).outcome == "accepted"
            assert scalar(db_url, "SELECT pin_x IS NULL AND box_w IS NULL FROM bench_pieces WHERE bench_id = %s "
                          "AND piece_id = 1", (bench,)) is True
            assert (await shop.apply(alana, bench, Undo(me, 5))).outcome == "accepted"
            assert (await shop.read(alana, bench)).pieces[1].place == Place(1, "large", PIN, BOX)
            refused = await shop.apply(alana, bench, Move(me, 1, Place(0, "small"), Pin(5001, 0)))
            assert refused.outcome == "bad_place"

    run(scenario())


def test_the_stored_log_replays_to_the_pins_and_boxes_a_read_shows(db_url: str) -> None:
    alana = owner_in(db_url)
    me = By(alana.person_id)
    commands: list[Command] = [
        add("a"), add("b"), add("c"), Move(me, 2, Place(0, "full"), PIN, None), Move(HER, 2, Place(2, "small")),
        Move(me, 3, Place(1, "medium"), box=BOX), Undo(me, 4), Move(me, 1, Place(0, "small"), Pin(1, 2), Box(100, 50)),
        Move(me, 1, Place(0, "small"), box=None)]

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            applied = [await shop.apply(alana, bench, c) for c in commands]
            log = await shop.log(alana, bench)
            view = await shop.read(alana, bench)
            final = replay([row.command for row in log], RULES, "desk")[-1].state
            assert [row.outcome for row in log] == [a.outcome for a in applied]
            assert [p.place for p in view.pieces] == [p.place for p in final.pieces]
            assert {p.id: (p.place.pin, p.place.box) for p in view.pieces} == {
                1: (Pin(1, 2), None), 2: (PIN, None), 3: (None, BOX)}

    run(scenario())


def test_a_log_row_written_before_pins_replays_as_it_did(db_url: str) -> None:
    alana = owner_in(db_url)
    me = By(alana.person_id)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = (await shop.open(alana, "desk")).id
            for c in (add("a"), add("b"), Move(me, 1, Place(0, "small"), PIN, BOX)):
                await shop.apply(alana, bench, c)
            old = {"type": "move", "piece_id": 1, "place": {"order": 1, "size": "large"}}
            await aexecute(db_url, "UPDATE bench_commands SET command = %s WHERE bench_id = %s AND seq = 3", (Jsonb(old), bench))
            log = await shop.log(alana, bench)
            assert log[2].command == Move(me, 1, Place(1, "large"))
            final = replay([row.command for row in log], RULES, "desk")[-1].state
            assert [(p.id, p.place) for p in final.pieces] == [(2, Place(0, "small")), (1, Place(1, "large"))]

    run(scenario())
