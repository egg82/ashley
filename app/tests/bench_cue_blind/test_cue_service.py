"""Her cue over the real Postgres workshop: logged and told once to the owner's screens as `BenchCued` and never as
`BenchChanged`; a refusal told to no one; another person's or household's bench, a closed bench and a removed piece
handled as for any command; a cue no change of the bench (pieces, `changes`, last change, `undo_next`)."""

import pytest
from ashley.live.events import Shown
from ashley.workshop.commands import Cue, Remove
from ashley.workshop.model import Owner
from ashley.workshop.workshop import BenchClosed, BenchNotFound, Workshop
from bench_cue_blind_support import HER, add_note, add_video, changed, cue, cued, undo, workshop, world
from contract.conversations_support import run
from live_support import FakeLive


async def with_video(shop: Workshop, owner: Owner) -> int:
    bench = await shop.open(owner, "tv")
    await shop.apply(owner, bench.id, add_video())
    await shop.apply(owner, bench.id, add_note(HER))
    return bench.id


def test_an_accepted_cue_is_logged_and_told_once_to_the_owner_as_a_cue_not_a_change(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            got = await shop.apply(w.alana, bench_id, cue(1, "seek", 42.5))
            assert got.outcome == "accepted" and got.seq == 3
            await shop.apply(w.alana, bench_id, cue(1, "play"))
            sent = cued(live)
            assert [(c.bench_id, c.piece_id, c.action, c.seconds) for c in sent] == [
                (bench_id, 1, "seek", 42.5), (bench_id, 1, "play", None)]
            assert all(c.shown == Shown(w.alana.household_id, w.alana.person_id) for c in sent)
            assert [c.seq for c in changed(live)] == [1, 2]

    run(scenario())


def test_a_cue_is_in_the_log_as_hers_and_survives_being_read_back(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            await shop.apply(w.alana, bench_id, cue(1, "seek", 9.5))
            await shop.apply(w.alana, bench_id, cue(1, "pause"))
            rows = await shop.log(w.alana, bench_id)
            assert [(r.seq, r.outcome) for r in rows] == [(1, "accepted"), (2, "accepted"), (3, "accepted"), (4, "accepted")]
            assert rows[2].command == Cue(HER, 1, "seek", 9.5)
            assert rows[3].command == Cue(HER, 1, "pause", None)
            assert [r.by.author for r in rows[2:]] == ["ashley", "ashley"]

    run(scenario())


def test_a_cue_changes_no_piece_no_change_and_not_undo_next(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            before = await shop.read(w.alana, bench_id)
            for command in (cue(1, "play"), cue(1, "seek", 0), cue(1, "pause")):
                await shop.apply(w.alana, bench_id, command)
            after = await shop.read(w.alana, bench_id)
            assert after.pieces == before.pieces
            assert after.changes == before.changes
            assert after.undo_next == before.undo_next == 2
            assert [r.seq for r in after.recent] == [1, 2, 3, 4, 5]

    run(scenario())


def test_a_cue_does_not_move_the_benchs_last_change(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            before = (await shop.read(w.alana, bench_id)).bench.last_changed_at
            assert before is not None
            await shop.apply(w.alana, bench_id, cue(1, "play"))
            assert (await shop.read(w.alana, bench_id)).bench.last_changed_at == before
            listed = [b for b in await shop.open_benches(w.alana) if b.id == bench_id]
            assert [b.last_changed_at for b in listed] == [before]

    run(scenario())


def test_the_undo_walk_served_passes_over_cues_and_an_undo_naming_one_is_nothing_to_undo(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            await shop.apply(w.alana, bench_id, cue(1, "play"))
            assert (await shop.read(w.alana, bench_id)).undo_next == 2
            await shop.apply(w.alana, bench_id, add_note(HER))
            await shop.apply(w.alana, bench_id, cue(1, "pause"))
            assert (await shop.read(w.alana, bench_id)).undo_next == 4
            refused = await shop.apply(w.alana, bench_id, undo(3, HER))
            assert refused.outcome == "nothing_to_undo"
            assert (await shop.read(w.alana, bench_id)).undo_next == 4

    run(scenario())


def test_a_refused_cue_is_logged_refused_and_told_to_no_one(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            told = len(live.published)
            outcomes = [(await shop.apply(w.alana, bench_id, c)).outcome for c in (
                cue(2, "play"), cue(1, "seek"), cue(1, "play", 3), cue(1, "seek", -1), cue(1, "seek", 360_000),
                cue(99, "pause"))]
            assert outcomes == ["not_video", "bad_cue", "bad_cue", "bad_cue", "bad_cue", "no_such_piece"]
            assert len(live.published) == told and cued(live) == []
            rows = await shop.log(w.alana, bench_id)
            assert [r.outcome for r in rows[2:]] == outcomes
            assert (await shop.read(w.alana, bench_id)).undo_next == 2

    run(scenario())


def test_a_cue_on_a_removed_piece_is_no_such_piece_and_told_to_no_one(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            await shop.apply(w.alana, bench_id, Remove(HER, 1))
            got = await shop.apply(w.alana, bench_id, cue(1, "play"))
            assert got.outcome == "no_such_piece" and cued(live) == []

    run(scenario())


def test_another_persons_or_households_bench_is_absent_and_nothing_is_told(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            told = len(live.published)
            for stranger in (w.sam, w.zed):
                with pytest.raises(BenchNotFound):
                    await shop.apply(stranger, bench_id, cue(1, "play"))
            assert len(live.published) == told and cued(live) == []
            assert len(await shop.log(w.alana, bench_id)) == 2

    run(scenario())


def test_a_cue_on_a_closed_bench_is_refused_like_any_command(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench_id = await with_video(shop, w.alana)
            await shop.close(w.alana, bench_id)
            with pytest.raises(BenchClosed):
                await shop.apply(w.alana, bench_id, cue(1, "play"))
            assert cued(live) == [] and len(await shop.log(w.alana, bench_id)) == 2

    run(scenario())


def test_a_cue_is_told_to_the_bench_it_was_made_on_when_two_benches_play(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            first, second = await with_video(shop, w.alana), await with_video(shop, w.alana)
            await shop.apply(w.alana, second, cue(1, "play"))
            await shop.apply(w.alana, first, cue(1, "pause"))
            assert [(c.bench_id, c.action) for c in cued(live)] == [(second, "play"), (first, "pause")]

    run(scenario())


def test_each_person_hears_cues_on_their_own_bench_only(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            alana, sam = await with_video(shop, w.alana), await with_video(shop, w.sam)
            await shop.apply(w.sam, sam, cue(1, "play"))
            await shop.apply(w.alana, alana, cue(1, "play"))
            assert [c.shown.person_id for c in cued(live)] == [w.sam.person_id, w.alana.person_id]

    run(scenario())
