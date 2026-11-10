"""A bench's shelf and its reopening over a real database: an archived piece is stored off the layout and out of the
bench's piece count, read back on its shelf with its last change, restored and undone as `decide` says, and the stored
log replays to the stored layout and shelf; closed benches are listed, most recently closed first, and reopen to take
commands again, the owner's alone."""

import pytest
from ashley import logs
from ashley.workshop.commands import Archive, Command, Edit, Remove, Restore, Undo
from ashley.workshop.decide import replay
from ashley.workshop.model import HER, By, Place, Text
from ashley.workshop.workshop import BenchClosed, BenchNotFound
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import run
from test_workshop_postgres import RULES, add, people, workshop_on


def test_an_archived_piece_is_stored_on_the_shelf_and_the_log_replays_to_layout_and_shelf(db_url: str) -> None:
    alana, _, _ = people(db_url)
    me = By(alana.person_id)
    commands: list[Command] = [
        add(alana, "a", "one"), add(alana, "b"), add(alana, "c"), Archive(HER, 1), Archive(me, 3),
        Edit(me, 1, 1, Text("x", "")), Restore(me, 3), Undo(HER, 7), Restore(me, 9), Undo(me, 4), Remove(me, 2)]

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, "desk")
            outcomes = [(await shop.apply(alana, bench.id, c)).outcome for c in commands]
            assert outcomes == ["accepted"] * 5 + ["no_such_piece", "accepted", "accepted", "no_such_piece",
                                                   "accepted", "accepted"]
            view = await shop.read(alana, bench.id)
            decided = replay([row.command for row in await shop.log(alana, bench.id)], RULES)[-1].state
            assert view.pieces == decided.pieces and view.shelf == decided.shelf
            assert [p.id for p in view.pieces] == [1] and [p.id for p in view.shelf] == [3]
            assert view.shelf[0].place == Place(1, "medium") and view.shelf[0].text == Text("c", "")
            assert view.changes[3].by == HER and view.bench.piece_count == 1
            assert [b.piece_count for b in await shop.open_benches(alana)] == [1]

    run(scenario())


def test_closed_benches_are_listed_newest_closed_first_and_reopen_to_take_commands(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    alana, sam, stranger = people(db_url)
    logs.setup()

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            first, second, third = [await shop.open(alana, t) for t in ("desk", "lamp", "shed")]
            await shop.apply(alana, first.id, add(alana))
            await shop.close(alana, second.id)
            await shop.close(alana, first.id)
            assert [b.id for b in await shop.closed_benches(alana)] == [first.id, second.id]
            assert (await shop.closed_benches(alana))[0].piece_count == 1
            assert await shop.closed_benches(sam) == [] == await shop.closed_benches(stranger)
            for other in (sam, stranger):
                with pytest.raises(BenchNotFound):
                    await shop.reopen(other, first.id)
            reopened = await shop.reopen(alana, first.id)
            assert reopened.closed_at is None and reopened.opened_at == first.opened_at
            assert await shop.reopen(alana, first.id) == reopened
            assert [b.id for b in await shop.open_benches(alana)] == [third.id, first.id]
            assert [b.id for b in await shop.closed_benches(alana)] == [second.id]
            assert (await shop.apply(alana, first.id, add(alana))).outcome == "accepted"
            with pytest.raises(BenchClosed):
                await shop.apply(alana, second.id, Archive(HER, 1))

    run(scenario())
    out = capsys.readouterr().out
    assert out.count("workshop.reopened") == 1 and out.count("workshop.closed") == 2
