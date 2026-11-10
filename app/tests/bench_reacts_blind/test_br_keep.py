"""`reaction_ages` and the keeping of reaction records (`reacted`'s `keep_s`) over a real database."""

import pytest
from bench_reacts_blind_support import world
from contract.conversations_support import run, scalar


def test_reaction_ages_are_newest_first_and_only_those_in_the_window(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            other = await w.bench(title="other")
            seqs = [await w.person_adds(bench)]
            for v in range(1, 4):
                seqs.append(await w.person_edits(bench, seqs[0], v))
            for s in seqs:
                await w.workshop.reacted(w.home.id, bench, s, 1e9)
            await w.workshop.reacted(w.home.id, other, await w.person_adds(other), 1e9)
            for s, age in zip(seqs, (800.0, 500.0, 200.0, 50.0)):
                w.age_reaction(bench, s, age)
            ages = await w.workshop.reaction_ages(bench, 900)
            assert [round(a, -1) for a in ages] == [50, 200, 500, 800]
            assert all(ages[i] <= ages[i + 1] for i in range(len(ages) - 1))
            assert [round(a, -1) for a in await w.workshop.reaction_ages(bench, 600)] == [50, 200, 500]
            assert await w.workshop.reaction_ages(bench, 10) == ()
            assert len(await w.workshop.reaction_ages(other, 900)) == 1
    run(go())


def test_a_bench_nothing_reacted_to_has_no_ages(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            assert await w.workshop.reaction_ages(bench, 1e6) == ()
    run(go())


def test_records_older_than_keep_go_when_the_next_is_written_and_in_limit_ones_stay(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            other = await w.bench(title="other")
            piece = await w.person_adds(bench)
            seqs = [piece] + [await w.person_edits(bench, piece, v) for v in range(1, 4)]
            oseq = await w.person_adds(other)
            for s in seqs[:3]:
                await w.workshop.reacted(w.home.id, bench, s, 1e9)
            await w.workshop.reacted(w.home.id, other, oseq, 1e9)
            for s, age in zip(seqs[:3], (5000.0, 2000.0, 100.0)):
                w.age_reaction(bench, s, age)
            w.age_reaction(other, oseq, 9000.0)
            await w.workshop.reacted(w.home.id, bench, seqs[3], 1000.0)
            assert w.reaction_rows(bench) == [seqs[2], seqs[3]]
            assert w.reaction_rows(other) == [oseq]
    run(go())


def test_the_newest_record_always_stays_however_old(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            seq = await w.person_adds(bench)
            await w.workshop.reacted(w.home.id, bench, seq, 1000.0)
            w.age_reaction(bench, seq, 50000.0)
            await w.workshop.reacted(w.home.id, bench, seq, 1000.0)
            assert w.reaction_rows(bench) == [seq]
            assert w.mark(bench) == seq
    run(go())


def test_the_keep_is_the_argument(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            e1 = await w.person_edits(bench, piece, 1)
            await w.workshop.reacted(w.home.id, bench, piece, 1e9)
            w.age_reaction(bench, piece, 3000.0)
            await w.workshop.reacted(w.home.id, bench, e1, 5000.0)
            assert w.reaction_rows(bench) == [piece, e1]
            await w.workshop.reacted(w.home.id, bench, e1, 1000.0)
            assert w.reaction_rows(bench) == [e1]
    run(go())


def test_a_bench_nobody_opened_in_this_household_reads_as_unavailable_not_as_marked(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            with pytest.raises(Exception):
                await w.workshop.reacted(w.home.id, 987654, 1, 1000.0)
            assert scalar(db_url, "SELECT count(*) FROM bench_reactions") == 0
    run(go())


def test_recording_a_mark_again_does_not_make_the_reaction_newer(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            seq = await w.person_adds(bench)
            await w.workshop.reacted(w.home.id, bench, seq, 1e9)
            w.age_reaction(bench, seq, 600.0)
            await w.workshop.reacted(w.home.id, bench, seq, 1e9)
            [age] = await w.workshop.reaction_ages(bench, 900)
            assert age > 500
    run(go())
