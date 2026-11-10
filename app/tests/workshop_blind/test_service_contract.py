"""The Postgres `Workshop` through the abstract interface alone: open, list, close, read, apply, log; ownership and
households; atomic numbering under races; what is logged and what is announced on Live."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from ashley import logs
from ashley.live.events import BenchChanged, Shown
from ashley.workshop.commands import Add, Command, piece_of
from ashley.workshop.decide import Accepted
from ashley.workshop.model import HER, By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Applied, BenchClosed, BenchNotFound, UnknownOwner, Workshop
from blind_support import RULES, add, edit, fold, move, remove, undo
from contract.conversations_support import TouchDatabase, run
from service_support import CommittedLive, changed, rows, workshop, world

TEXT = 'é✓"\\\n\t'


def by(owner: Owner) -> By:
    return By(owner.person_id)


async def opened(w: Workshop, owner: Owner, title: str = "t") -> int:
    return (await w.open(owner, title)).id


async def applied(w: Workshop, owner: Owner, bench_id: int, *commands: Command) -> list[Applied]:
    return [await w.apply(owner, bench_id, c) for c in commands]


def mine(owner: Owner, command: Command) -> Command:
    """`command` made by `owner`."""
    return replace(command, by=by(owner))


# --- open, list, close ------------------------------------------------------------------------------------------


def test_open_makes_an_empty_open_bench_of_the_owner_with_its_thread(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench = await s.open(w.alana, "abc")
            assert (bench.household_id, bench.owner_id, bench.title, bench.closed_at) == (
                w.alana.household_id, w.alana.person_id, "abc", None)
            assert bench.thread == f"bench:{bench.id}" and bench.opened_at.tzinfo is not None
            assert abs(datetime.now(UTC) - bench.opened_at) < timedelta(minutes=2)
            view = await s.read(w.alana, bench.id)
            assert (view.bench, view.pieces, view.recent) == (bench, (), ())
            assert await s.log(w.alana, bench.id) == []

    run(scenario())


@pytest.mark.parametrize("title", ["", " ", "\n\t ", "abcdef", "x" * 500])
def test_a_bad_title_is_a_value_error_before_the_database_is_touched(title: str) -> None:
    database = TouchDatabase()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await PostgresWorkshop(database, RULES).open(Owner(1, 1), title)

    run(scenario())
    assert database.touched == 0


def test_titles_of_one_to_the_limit_open_and_come_back_unchanged(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            for title in ("a", " a ", "ééééé", "😀😀😀😀😀"):
                assert (await s.open(w.alana, title)).title == title

    run(scenario())


def test_an_owner_who_is_not_a_person_of_that_household_is_unknown_and_nothing_is_written(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            for stranger in (Owner(w.alana.household_id, w.zed.person_id), Owner(w.zed.household_id, w.alana.person_id),
                             Owner(w.alana.household_id, 99999), Owner(99999, w.alana.person_id)):
                with pytest.raises(UnknownOwner):
                    await s.open(stranger, "abc")

    run(scenario())
    assert rows(db_url, "benches") == 0


def test_open_benches_are_the_owners_own_newest_first_and_never_closed_ones(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            first, second, third = [await opened(s, w.alana, n) for n in "123"]
            sams, zeds = await opened(s, w.sam), await opened(s, w.zed)
            await s.close(w.alana, second)
            assert [b.id for b in await s.open_benches(w.alana)] == [third, first]
            assert [b.id for b in await s.open_benches(w.sam)] == [sams]
            assert [b.id for b in await s.open_benches(w.zed)] == [zeds]
            await s.close(w.alana, third)
            await s.close(w.alana, first)
            assert await s.open_benches(w.alana) == []

    run(scenario())


def test_close_keeps_the_bench_readable_and_logged_but_unlisted(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            await applied(s, w.alana, bench_id, mine(w.alana, add("a", "x")))
            closed = await s.close(w.alana, bench_id)
            assert closed.id == bench_id and closed.closed_at is not None and closed.closed_at >= closed.opened_at
            assert closed.title == "t" and closed.owner_id == w.alana.person_id
            view = await s.read(w.alana, bench_id)
            assert view.bench == closed and [p.text for p in view.pieces] == [Text("a", "x")]
            assert [row.seq for row in await s.log(w.alana, bench_id)] == [1]
            assert await s.open_benches(w.alana) == []

    run(scenario())


def test_closing_a_closed_bench_changes_nothing_and_says_so_only_once(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    w = world(db_url)
    capsys.readouterr()

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            first = await s.close(w.alana, bench_id)
            await asyncio.sleep(0.02)
            assert await s.close(w.alana, bench_id) == first
            assert (await s.read(w.alana, bench_id)).bench == first

    run(scenario())
    out = capsys.readouterr().out
    assert out.count("event=workshop.closed") == 1 and out.count("event=workshop.opened") == 1


# --- whose bench it is ------------------------------------------------------------------------------------------


def test_anothers_bench_is_exactly_as_absent_as_one_that_does_not_exist(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            await applied(s, w.alana, bench_id, mine(w.alana, add("a")))
            before = await s.read(w.alana, bench_id)
            for who in (w.sam, w.zed, Owner(w.alana.household_id, 99999)):
                for call in (s.read(who, bench_id), s.log(who, bench_id), s.close(who, bench_id),
                             s.apply(who, bench_id, add("b", by=by(who))), s.read(w.alana, bench_id + 1000)):
                    with pytest.raises(BenchNotFound):
                        await call
            for missing in (0, -1, bench_id + 1000):
                with pytest.raises(BenchNotFound):
                    await s.read(w.alana, missing)
            assert await s.read(w.alana, bench_id) == before          # none of those changed it
            assert (await s.read(w.alana, bench_id)).bench.closed_at is None

    run(scenario())
    assert rows(db_url, "bench_commands") == 1


# --- apply, read, log -------------------------------------------------------------------------------------------


def test_apply_numbers_every_command_from_one_refusals_too_and_names_the_piece(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            got = await applied(s, w.alana, bench_id, mine(w.alana, add("a", TEXT)), mine(w.alana, add("toolong!")),
                                mine(w.alana, add("b")), mine(w.alana, edit(1, 7)), mine(w.alana, remove(1)),
                                mine(w.alana, undo(4)), mine(w.alana, undo(5)))
            assert got == [Applied(1, "accepted", 1), Applied(2, "bad_title", None), Applied(3, "accepted", 3),
                           Applied(4, "stale_base", None), Applied(5, "accepted", 1),
                           Applied(6, "nothing_to_undo", None), Applied(7, "accepted", 1)]
            view = await s.read(w.alana, bench_id)
            assert [(p.id, p.place.order, p.text) for p in view.pieces] == [(1, 0, Text("a", TEXT)), (3, 1, Text("b", ""))]

    run(scenario())


def test_the_log_is_every_command_in_seq_order_as_sent_and_replays_to_the_bench(db_url: str) -> None:
    w = world(db_url)
    sent: list[Command] = [add("a", TEXT), add("b"), add("c"), add("d"), edit(2, 1, "z", "é" * 10), move(3, 0, "full"),
                           edit(2, 1), undo(5), remove(1), undo(9), undo(9), add("e", "x" * 11), undo(99), undo(1)]

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            await applied(s, w.alana, bench_id, *(mine(w.alana, c) for c in sent))
            log, view = await s.log(w.alana, bench_id), await s.read(w.alana, bench_id)
            assert [row.seq for row in log] == list(range(1, len(sent) + 1))
            assert [row.command for row in log] == [mine(w.alana, c) for c in sent]
            assert all(row.by == by(w.alana) and row.at.tzinfo is not None for row in log)
            assert [row.at for row in log] == sorted(row.at for row in log)
            replayed = fold(row.command for row in log)
            assert [row.outcome for row in log] == ["accepted" if isinstance(d, Accepted) else d.reason for d in replayed]
            assert [row.piece_id for row in log] == [piece_of(d.effect) if isinstance(d, Accepted) else None
                                                     for d in replayed]
            assert replayed[-1].state.pieces == view.pieces
            assert {"accepted"} < {row.outcome for row in log} and len({row.outcome for row in log}) > 4

    run(scenario())


def test_read_carries_only_the_latest_recent_commands_oldest_first(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            await applied(s, w.alana, bench_id, *(mine(w.alana, add(str(i))) for i in range(6)))
            view = await s.read(w.alana, bench_id)
            assert RULES.recent_commands == 4 and [row.seq for row in view.recent] == [3, 4, 5, 6]
            assert [row.outcome for row in view.recent] == ["accepted", "full", "full", "full"]
            assert view.recent == tuple((await s.log(w.alana, bench_id))[2:])

    run(scenario())


def test_her_commands_are_logged_as_hers_and_a_person_cannot_speak_for_another(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            await s.apply(w.alana, bench_id, add("a", by=HER))
            await s.apply(w.alana, bench_id, add("b", by=by(w.alana)))
            log = await s.log(w.alana, bench_id)
            assert [row.by.author for row in log] == ["ashley", "person"] and log[0].by == HER
            for liar in (by(w.sam), By(99999), by(w.zed)):
                with pytest.raises(ValueError):
                    await s.apply(w.alana, bench_id, add("c", by=liar))
            assert len(await s.log(w.alana, bench_id)) == 2

    run(scenario())


def test_a_mismatched_author_is_a_value_error_before_the_database_is_touched() -> None:
    database = TouchDatabase()

    async def scenario() -> None:
        with pytest.raises(ValueError):
            await PostgresWorkshop(database, RULES).apply(Owner(1, 1), 5, add("a", by=By(2)))

    run(scenario())
    assert database.touched == 0


def test_a_closed_bench_takes_no_command_and_logs_nothing(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            await applied(s, w.alana, bench_id, mine(w.alana, add("a")))
            await s.close(w.alana, bench_id)
            for command in (add("b"), add("toolong!"), remove(9), undo(1), undo(50)):
                with pytest.raises(BenchClosed):
                    await s.apply(w.alana, bench_id, mine(w.alana, command))
            assert [row.seq for row in await s.log(w.alana, bench_id)] == [1]

    run(scenario())
    assert rows(db_url, "bench_commands") == 1


def test_benches_number_their_commands_separately(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            one, two = await opened(s, w.alana), await opened(s, w.alana)
            await applied(s, w.alana, one, mine(w.alana, add("a")), mine(w.alana, add("b")))
            assert await s.apply(w.alana, two, mine(w.alana, add("c"))) == Applied(1, "accepted", 1)
            assert [p.id for p in (await s.read(w.alana, one)).pieces] == [1, 2]
            assert [p.id for p in (await s.read(w.alana, two)).pieces] == [1]

    run(scenario())


# --- racing ---------------------------------------------------------------------------------------------------


def test_racing_edits_on_one_base_accept_exactly_one(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            await s.apply(w.alana, bench_id, add("a", by=by(w.alana)))
            got = await asyncio.gather(*(s.apply(w.alana, bench_id, edit(1, 1, str(i), by=by(w.alana))) for i in range(5)))
            assert sorted(a.outcome for a in got) == ["accepted"] + ["stale_base"] * 4
            assert sorted(a.seq for a in got) == [2, 3, 4, 5, 6]
            assert (await s.read(w.alana, bench_id)).pieces[0].version == 2

    run(scenario())


def test_racing_adds_never_pass_the_limit_and_never_share_a_seq_or_an_id(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            bench_id = await opened(s, w.alana)
            got = await asyncio.gather(*(s.apply(w.alana, bench_id, add(str(i), by=by(w.alana))) for i in range(8)))
            assert sorted(a.outcome for a in got) == ["accepted"] * 3 + ["full"] * 5
            assert sorted(a.seq for a in got) == list(range(1, 9))
            view, log = await s.read(w.alana, bench_id), await s.log(w.alana, bench_id)
            assert len({p.id for p in view.pieces}) == 3 and [p.place.order for p in view.pieces] == [0, 1, 2]
            assert fold(row.command for row in log)[-1].state.pieces == view.pieces

    run(scenario())


# --- Live -----------------------------------------------------------------------------------------------------


def test_live_hears_of_an_accepted_command_after_it_committed_and_of_nothing_else(db_url: str) -> None:
    w = world(db_url)
    live = CommittedLive(db_url)

    async def scenario() -> None:
        async with workshop(db_url, live=live) as s:
            bench_id = await opened(s, w.alana)
            assert live.published == []                                  # opening is not a bench change
            await s.apply(w.alana, bench_id, add("a", by=by(w.alana)))
            await s.apply(w.alana, bench_id, add("toolong!", by=by(w.alana)))     # refused
            await s.apply(w.alana, bench_id, undo(2, by(w.alana)))                  # refused too
            await s.apply(w.alana, bench_id, add("b", by=HER))
            with pytest.raises(BenchNotFound):
                await s.apply(w.sam, bench_id, add("c", by=by(w.sam)))
            with pytest.raises(ValueError):
                await s.apply(w.alana, bench_id, add("c", by=by(w.sam)))
            await s.close(w.alana, bench_id)
            with pytest.raises(BenchClosed):
                await s.apply(w.alana, bench_id, add("c", by=by(w.alana)))
            await s.read(w.alana, bench_id)
            await s.log(w.alana, bench_id)
            await s.open_benches(w.alana)
            owner = Shown(w.alana.household_id, w.alana.person_id)
            assert changed(live) == [BenchChanged(owner, bench_id, 1), BenchChanged(owner, bench_id, 4)]
            assert len(live.published) == 2 and live.visible == [1, 4]

    run(scenario())


def test_live_is_told_of_a_command_by_her_as_well_and_to_the_owner_alone(db_url: str) -> None:
    w = world(db_url)
    live = CommittedLive(db_url)

    async def scenario() -> None:
        async with workshop(db_url, live=live) as s:
            bench_id = await opened(s, w.sam)
            await s.apply(w.sam, bench_id, Add(HER, "note", Text("a", ""), "small"))
            [event] = changed(live)
            assert event.shown == Shown(w.sam.household_id, w.sam.person_id) and event.shown.device_id is None

    run(scenario())
