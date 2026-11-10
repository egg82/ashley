"""Closed benches through the Postgres `Workshop`: listed most recently closed first, the owner's alone, and reopened as
they were."""

import pytest
from ashley import logs
from ashley.workshop.model import Owner
from ashley.workshop.workshop import BenchClosed, BenchNotFound
from contract.conversations_support import events, run
from shelf_service_support import A3, bench_of, by, do, workshop, world
from shelf_support import add, archive, edit, ids, restore


# --- closed benches ---------------------------------------------------------------------------------------------------------


def test_closed_benches_is_empty_for_a_person_with_none(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            await s.open(w.alana, "open")
            assert await s.closed_benches(w.alana) == [] and await s.closed_benches(w.zed) == []

    run(scenario())


def test_closed_benches_lists_closed_ones_most_recently_closed_first(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            one, two, three, four = [(await s.open(w.alana, str(n))).id for n in range(4)]
            await s.close(w.alana, two)
            await s.close(w.alana, one)
            await s.close(w.alana, three)
            listed = await s.closed_benches(w.alana)
            assert [b.id for b in listed] == [three, one, two]
            assert all(b.closed_at is not None for b in listed)
            stamps = [b.closed_at for b in listed if b.closed_at is not None]
            assert stamps == sorted(stamps, reverse=True)
            assert [b.id for b in await s.open_benches(w.alana)] == [four]

    run(scenario())


def test_closing_a_closed_bench_again_does_not_move_it_in_the_list(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            one, two = (await s.open(w.alana, "1")).id, (await s.open(w.alana, "2")).id
            await s.close(w.alana, one)
            await s.close(w.alana, two)
            await s.close(w.alana, one)
            assert [b.id for b in await s.closed_benches(w.alana)] == [two, one]

    run(scenario())


def test_a_closed_bench_carries_its_counts(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(1))
            before = (await s.open_benches(w.alana))[0]
            closed = await s.close(w.alana, b)
            [listed] = await s.closed_benches(w.alana)
            assert listed == closed
            assert (listed.piece_count, listed.last_changed_at, listed.opened_at, listed.title) == (
                2, before.last_changed_at, before.opened_at, before.title)
            assert listed.last_changed_at is not None

    run(scenario())


def test_closed_benches_are_the_owners_alone(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            mine = (await s.open(w.alana, "mine")).id
            theirs = (await s.open(w.sam, "sam")).id
            far = (await s.open(w.zed, "zed")).id
            for owner, bench in ((w.alana, mine), (w.sam, theirs), (w.zed, far)):
                await s.close(owner, bench)
            assert [b.id for b in await s.closed_benches(w.alana)] == [mine]
            assert [b.id for b in await s.closed_benches(w.sam)] == [theirs]
            assert [b.id for b in await s.closed_benches(w.zed)] == [far]

    run(scenario())


def test_a_closed_bench_reads_with_its_shelf_and_takes_no_command(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(2))
            await s.close(w.alana, b)
            assert ids((await s.read(w.alana, b)).shelf) == [2]
            for c in (archive(1, by(w.alana)), restore(2, by(w.alana)), add("x", by=by(w.alana))):
                with pytest.raises(BenchClosed):
                    await s.apply(w.alana, b, c)
            assert len(await s.log(w.alana, b)) == 4

    run(scenario())


def test_reopen_returns_the_bench_open_with_everything_as_it_was(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(2), edit(1, 1, "z", "Z"))
            open_before = await s.read(w.alana, b)
            await s.close(w.alana, b)
            closed_view = await s.read(w.alana, b)
            got = await s.reopen(w.alana, b)
            assert got.closed_at is None and got.id == b
            assert (got.opened_at, got.title, got.piece_count, got.last_changed_at) == (
                open_before.bench.opened_at, "t", 2, open_before.bench.last_changed_at)
            after = await s.read(w.alana, b)
            assert after.bench == got
            assert (after.pieces, after.shelf, after.recent) == (closed_view.pieces, closed_view.shelf,
                                                                 closed_view.recent) == (
                open_before.pieces, open_before.shelf, open_before.recent)
            assert await s.closed_benches(w.alana) == []
            assert [x.id for x in await s.open_benches(w.alana)] == [b]

    run(scenario())


def test_a_reopened_bench_takes_commands_again(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(2))
            await s.close(w.alana, b)
            await s.reopen(w.alana, b)
            got = await do(s, w.alana, b, restore(2), archive(1))
            assert [(g.seq, g.outcome) for g in got] == [(5, "accepted"), (6, "accepted")]
            assert ids((await s.read(w.alana, b)).shelf) == [1]

    run(scenario())


def test_reopening_an_open_bench_changes_nothing_and_logs_nothing(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            before = (await s.read(w.alana, b)).bench
            capsys.readouterr()
            assert await s.reopen(w.alana, b) == before
            assert await s.reopen(w.alana, b) == before
            assert events(capsys.readouterr().out, "workshop.reopened") == []

    run(scenario())


def test_reopen_twice_logs_once_and_the_second_returns_the_same_bench(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            await s.close(w.alana, b)
            capsys.readouterr()
            first = await s.reopen(w.alana, b)
            again = await s.reopen(w.alana, b)
            assert first == again
            got = events(capsys.readouterr().out, "workshop.reopened")
            assert len(got) == 1 and got[0]["bench"] == str(b)

    run(scenario())


def test_reopen_adds_nothing_to_the_command_log(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            await s.close(w.alana, b)
            await s.reopen(w.alana, b)
            assert [r.seq for r in await s.log(w.alana, b)] == [1, 2, 3]

    run(scenario())


def test_close_reopen_close_orders_by_the_latest_close(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            one, two = (await s.open(w.alana, "1")).id, (await s.open(w.alana, "2")).id
            await s.close(w.alana, one)
            await s.close(w.alana, two)
            await s.reopen(w.alana, one)
            await s.close(w.alana, one)
            assert [b.id for b in await s.closed_benches(w.alana)] == [one, two]

    run(scenario())


def test_reopen_of_another_persons_or_a_missing_bench_is_not_found_and_changes_nothing(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = (await s.open(w.alana, "mine")).id
            closed = await s.close(w.alana, b)
            for owner in (w.sam, w.zed):
                with pytest.raises(BenchNotFound):
                    await s.reopen(owner, b)
            for missing in (0, b + 100, -1):
                with pytest.raises(BenchNotFound):
                    await s.reopen(w.alana, missing)
            assert (await s.read(w.alana, b)).bench == closed
            assert [x.id for x in await s.closed_benches(w.alana)] == [b]

    run(scenario())


def test_an_unknown_owner_cannot_see_closed_benches(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = (await s.open(w.alana, "mine")).id
            await s.close(w.alana, b)
            stranger = Owner(w.alana.household_id, w.zed.person_id)
            assert await s.closed_benches(stranger) == []

    run(scenario())
