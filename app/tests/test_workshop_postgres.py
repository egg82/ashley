"""The Workshop over a real database: open, list, close and read a person's benches; another person's or household's
bench is not found; every command is logged, accepted or refused, and the stored log replayed from empty reproduces
the stored pieces; racing commands on one bench are decided one after the other; an accepted command is announced on
Live to the owner alone, a refusal not at all; nothing of a title or body reaches the logs."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from ashley import logs, services
from ashley.db.pool import PoolDatabase
from ashley.live.events import BenchChanged, Event, Shown, Watcher
from ashley.live.fanout import Subscription
from ashley.live.live import Live
from ashley.workshop.commands import Add, Command, Edit, Move, Remove, Undo
from ashley.workshop.decide import Accepted, replay
from ashley.workshop.model import HER, By, Owner, Place, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import BenchClosed, BenchNotFound, UnknownOwner, Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

RULES = Rules({"note": Kind("note", "stored", "Note", 20)}, max_pieces=4, title_max_chars=12, recent_commands=3, undo_window=100)
SECRET = "plans-for-the-shed"


class Heard(Live):
    def __init__(self) -> None:
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)

    def subscribe(self, viewer: Watcher) -> Subscription:
        raise NotImplementedError


@asynccontextmanager
async def workshop_on(url: str) -> AsyncGenerator[Workshop]:
    database = PoolDatabase(url)
    await database.open()
    try:
        yield PostgresWorkshop(database, RULES)
    finally:
        await database.close()


def people(url: str) -> tuple[Owner, Owner, Owner]:
    home, other = household(url), household(url, "next door")
    return Owner(home, person(url, home)), Owner(home, person(url, home)), Owner(other, person(url, other))


def add(owner: Owner, title: str = "n", body: str = "") -> Add:
    return Add(By(owner.person_id), "note", Text(title, body), "medium")


def test_benches_open_list_newest_first_and_a_closed_one_is_kept_but_not_listed(db_url: str) -> None:
    alana, sam, _ = people(db_url)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            first = await shop.open(alana, "desk")
            second = await shop.open(alana, "lamp")
            await shop.open(sam, "sams")
            assert [b.id for b in await shop.open_benches(alana)] == [second.id, first.id]
            assert first.thread == f"bench:{first.id}" and first.closed_at is None
            closed = await shop.close(alana, first.id)
            assert closed.closed_at is not None
            assert await shop.close(alana, first.id) == closed
            assert [b.id for b in await shop.open_benches(alana)] == [second.id]
            assert (await shop.read(alana, first.id)).bench == closed
            with pytest.raises(BenchClosed):
                await shop.apply(alana, first.id, add(alana))
            with pytest.raises(ValueError):
                await shop.open(alana, " ")
            with pytest.raises(ValueError):
                await shop.open(alana, "a\x00b")

    run(scenario())


def test_another_persons_or_households_bench_is_not_found(db_url: str) -> None:
    alana, sam, stranger = people(db_url)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, "desk")
            for other in (sam, stranger, Owner(stranger.household_id, alana.person_id)):
                for call in (shop.read(other, bench.id), shop.close(other, bench.id), shop.log(other, bench.id),
                             shop.apply(other, bench.id, Add(HER, "note", Text("n", ""), "small"))):
                    with pytest.raises(BenchNotFound):
                        await call
            with pytest.raises(UnknownOwner):
                await shop.open(Owner(stranger.household_id, alana.person_id), "x")
            with pytest.raises(ValueError):
                await shop.apply(alana, bench.id, add(sam))

    run(scenario())


def test_the_stored_log_replays_to_the_stored_pieces_with_every_outcome(db_url: str) -> None:
    alana, _, _ = people(db_url)
    me = By(alana.person_id)
    commands: list[Command] = [
        add(alana, "a", "one"), add(alana, "b"), Edit(HER, 1, 1, Text("a2", "two")), Edit(me, 1, 1, Text("x", "")),
        Move(me, 2, Place(0, "full")), Remove(HER, 9), Undo(me, 5), Undo(me, 3), Remove(me, 1), Undo(HER, 9),
        add(alana, "c", "y" * 21), Undo(me, 6)]

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, "desk")
            applied = [await shop.apply(alana, bench.id, c) for c in commands]
            log = await shop.log(alana, bench.id)
            view = await shop.read(alana, bench.id)
            decided = replay([row.command for row in log], RULES)
            assert [a.seq for a in applied] == list(range(1, len(commands) + 1))
            assert [row.outcome for row in log] == [a.outcome for a in applied]
            assert [row.command for row in log] == commands
            assert view.pieces == decided[-1].state.pieces
            assert [r.outcome for r in log] == ["accepted" if isinstance(d, Accepted) else d.reason for d in decided]
            assert [r.seq for r in view.recent] == [10, 11, 12]

    run(scenario())


def test_racing_commands_on_one_bench_are_each_decided_against_the_other(db_url: str) -> None:
    alana, _, _ = people(db_url)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, "desk")
            await shop.apply(alana, bench.id, add(alana))
            edits = [Edit(HER, 1, 1, Text("her", "")), Edit(By(alana.person_id), 1, 1, Text("his", ""))]
            got = await asyncio.gather(*(shop.apply(alana, bench.id, e) for e in edits))
            assert sorted(a.outcome for a in got) == ["accepted", "stale_base"]
            assert sorted(a.seq for a in got) == [2, 3]
            assert (await shop.read(alana, bench.id)).pieces[0].version == 2

    run(scenario())


def test_an_accepted_command_is_shown_to_the_owner_and_a_refusal_to_no_one(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    alana, _, _ = people(db_url)
    heard = Heard()
    services.register(Live, heard)
    logs.setup()

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, SECRET[:12])
            await shop.apply(alana, bench.id, add(alana, SECRET[:12], SECRET))
            await shop.apply(alana, bench.id, Remove(HER, 5))
            assert heard.events == [BenchChanged(Shown(alana.household_id, alana.person_id), bench.id, 1)]

    run(scenario())
    out = capsys.readouterr().out
    assert "workshop.command" in out and "outcome=no_such_piece" in out and "by=ashley" in out
    assert SECRET[:8] not in out


def test_pressing_undo_again_takes_back_the_next_older_command_and_an_undo_is_not_undone(db_url: str) -> None:
    alana, _, _ = people(db_url)
    me = By(alana.person_id)

    async def scenario() -> None:
        async with workshop_on(db_url) as shop:
            bench = await shop.open(alana, "desk")
            for command in (add(alana, "a"), add(alana, "b"), Edit(HER, 2, 1, Text("b2", ""))):
                await shop.apply(alana, bench.id, command)
            seen: list[tuple[int | None, str]] = []
            while (target := (await shop.read(alana, bench.id)).undo_next) is not None:
                seen.append((target, (await shop.apply(alana, bench.id, Undo(me, target))).outcome))
            assert seen == [(3, "accepted"), (2, "accepted"), (1, "accepted")]
            view = await shop.read(alana, bench.id)
            assert view.pieces == () and view.undo_next is None
            assert (await shop.apply(alana, bench.id, Undo(me, 5))).outcome == "nothing_to_undo"
            assert (await shop.apply(alana, bench.id, Undo(me, 3))).outcome == "changed_since"

    run(scenario())
