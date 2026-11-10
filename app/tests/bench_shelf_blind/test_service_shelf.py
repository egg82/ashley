"""The Postgres `Workshop` with a shelf: what `read` shows, what the log replays to, the pieces count, racing commands,
what is announced and logged, and closed benches that are listed and reopened."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from ashley import logs
from ashley.live.events import Shown
from ashley.workshop.decide import Accepted, replay
from ashley.workshop.model import Text
from ashley.workshop.workshop import BenchNotFound
from contract.conversations_support import events, run
from live_support import FakeLive
from shelf_service_support import A3, bench_of, by, changed, do, workshop, world
from shelf_support import RULES, add, archive, core, edit, ids, move, remove, restore, undo


# --- read -------------------------------------------------------------------------------------------------------------


def test_read_shows_the_layout_and_the_shelf_most_recently_archived_first(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(1), archive(3))
            view = await s.read(w.alana, b)
            assert ids(view.pieces) == [2] and ids(view.shelf) == [3, 1]
            assert [p.place.order for p in view.pieces] == [0]
            assert [(p.text, p.version, p.kind, p.place.size) for p in view.shelf] == [
                (Text("c", "C"), 1, "note", "large"), (Text("a", "A"), 1, "note", "small")]

    run(scenario())


def test_a_bench_with_nothing_archived_has_an_empty_shelf(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            assert (await s.read(w.alana, b)).shelf == ()

    run(scenario())


def test_the_shelf_survives_a_fresh_service_on_the_same_database(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(2))
        async with workshop(db_url) as s:
            assert ids((await s.read(w.alana, b)).shelf) == [2]
            assert [r.outcome for r in await s.log(w.alana, b)] == ["accepted"] * 4

    run(scenario())


def test_archive_keeps_the_body_and_a_restore_brings_it_back_last_at_its_size(db_url: str) -> None:
    w = world(db_url)
    body = 'é✓"\\\n\t'

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, add("a", body, size="medium"), add("b"), edit(1, 1, "z", body + "!"),
                               archive(1), restore(1))
            view = await s.read(w.alana, b)
            assert ids(view.pieces) == [2, 1] and view.shelf == ()
            first = view.pieces[1]
            assert (first.text, first.version, first.place.order, first.place.size) == (Text("z", body + "!"), 2, 1,
                                                                                         "medium")

    run(scenario())


def test_applied_names_the_piece_an_archive_or_restore_changed(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            got = await do(s, w.alana, b, archive(2), restore(2), archive(9), restore(9))
            assert [(g.seq, g.outcome, g.piece_id) for g in got] == [
                (4, "accepted", 2), (5, "accepted", 2), (6, "no_such_piece", None), (7, "no_such_piece", None)]

    run(scenario())


def test_changes_covers_a_shelved_piece_with_the_archive_that_shelved_it(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            await s.apply(w.alana, b, archive(2, by(w.alana)))
            await s.apply(w.alana, b, restore(2, by(w.alana)))
            await s.apply(w.alana, b, archive(2, by(w.alana)))
            view = await s.read(w.alana, b)
            assert view.shelf[0].changed_by == 6
            change = view.changes[2]
            assert change.by == by(w.alana) and abs(datetime.now(UTC) - change.at) < timedelta(minutes=2)
            assert set(view.changes) == {1, 2, 3}

    run(scenario())


# --- the log replays to the bench ---------------------------------------------------------------------------------------


def test_the_log_replayed_from_empty_reproduces_the_pieces_the_shelf_and_every_outcome(db_url: str) -> None:
    w = world(db_url)
    script = [*A3, archive(2), add("d"), restore(2), remove(1), restore(1), archive(3), archive(3), undo(8),
              archive(1), undo(5), restore(2), move(2, 0, "full"), undo(11), edit(3, 1)]

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *script)
            rows = await s.log(w.alana, b)
            decisions = replay([r.command for r in rows], RULES)
            assert [r.outcome for r in rows] == [
                "accepted" if isinstance(d, Accepted) else d.reason for d in decisions]
            view = await s.read(w.alana, b)
            final = decisions[-1].state
            assert view.pieces == final.pieces and view.shelf == final.shelf
            assert "no_such_piece" in {r.outcome for r in rows} and view.shelf

    run(scenario())


def test_the_log_records_archive_and_restore_commands_as_given(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, add("a"), archive(1), restore(1))
            rows = await s.log(w.alana, b)
            assert [r.command for r in rows[1:]] == [archive(1, by(w.alana)), restore(1, by(w.alana))]
            assert [r.piece_id for r in rows] == [1, 1, 1]

    run(scenario())


def test_bench_view_recent_names_the_archive_and_restore(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, add("a"), archive(1), restore(1))
            view = await s.read(w.alana, b)
            assert [r.command for r in view.recent][1:] == [archive(1, by(w.alana)), restore(1, by(w.alana))]

    run(scenario())


# --- pieces count and the limit ----------------------------------------------------------------------------------------


def test_piece_count_is_the_layout_only_in_read_and_in_both_lists(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(1), archive(2))
            assert (await s.read(w.alana, b)).bench.piece_count == 1
            assert [x.piece_count for x in await s.open_benches(w.alana)] == [1]
            await s.close(w.alana, b)
            assert [x.piece_count for x in await s.closed_benches(w.alana)] == [1]
            assert (await s.read(w.alana, b)).bench.piece_count == 1

    run(scenario())


def test_archiving_everything_leaves_piece_count_zero(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            await bench_of(s, w.alana, *A3, archive(1), archive(2), archive(3))
            assert (await s.open_benches(w.alana))[0].piece_count == 0

    run(scenario())


def test_the_shelf_may_outgrow_max_pieces_through_the_service(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await s.open(w.alana, "t")
            for n in range(RULES.max_pieces + 2):
                got = await do(s, w.alana, b.id, add("x"), archive(2 * n + 1))
                assert [g.outcome for g in got] == ["accepted", "accepted"]
            view = await s.read(w.alana, b.id)
            assert view.pieces == () and len(view.shelf) == RULES.max_pieces + 2

    run(scenario())


def test_restore_onto_a_full_bench_is_full_through_the_service(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(1), add("d"))
            got = (await do(s, w.alana, b, restore(1)))[0]
            assert (got.outcome, got.piece_id) == ("full", None)
            view = await s.read(w.alana, b)
            assert ids(view.shelf) == [1] and len(view.pieces) == 3

    run(scenario())


def test_undo_of_an_archive_is_full_through_the_service_and_works_with_room(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(2), add("d"))
            assert (await do(s, w.alana, b, undo(4)))[0].outcome == "full"
            await do(s, w.alana, b, remove(5))
            assert (await do(s, w.alana, b, undo(4)))[0].outcome == "accepted"
            view = await s.read(w.alana, b)
            assert ids(view.pieces) == [1, 2, 3] and view.shelf == ()
            assert [core(p) for p in view.pieces] == [(1, "note", Text("a", "A"), "small"),
                                                      (2, "note", Text("b", "B"), "medium"),
                                                      (3, "note", Text("c", "C"), "large")]

    run(scenario())


# --- races ---------------------------------------------------------------------------------------------------------------


def test_two_archives_of_one_piece_racing_accept_one_and_refuse_the_other(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            got = await asyncio.gather(*[do(s, w.alana, b, archive(2)) for _ in range(6)])
            outcomes = sorted(g[0].outcome for g in got)
            assert outcomes == ["accepted"] + ["no_such_piece"] * 5
            assert sorted(g[0].seq for g in got) == [4, 5, 6, 7, 8, 9]
            view = await s.read(w.alana, b)
            assert ids(view.shelf) == [2] and ids(view.pieces) == [1, 3]

    run(scenario())


def test_a_restore_racing_an_add_for_the_last_slot_never_overfills_the_layout(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(1))
            got = await asyncio.gather(do(s, w.alana, b, restore(1)), do(s, w.alana, b, add("d")),
                                       do(s, w.alana, b, restore(1)))
            outcomes = sorted(g[0].outcome for g in got)
            assert outcomes.count("accepted") == 1
            view = await s.read(w.alana, b)
            assert len(view.pieces) == 3
            assert not set(ids(view.pieces)) & set(ids(view.shelf))
            rows = await s.log(w.alana, b)
            decisions = replay([r.command for r in rows], RULES)
            assert decisions[-1].state.pieces == view.pieces and decisions[-1].state.shelf == view.shelf

    run(scenario())


# --- live, logs ------------------------------------------------------------------------------------------------------------


def test_an_accepted_archive_or_restore_is_announced_to_the_owner_and_a_refusal_is_not(db_url: str) -> None:
    w = world(db_url)
    live = FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as s:
            b = await bench_of(s, w.alana, add("a"))
            live.published.clear()
            await do(s, w.alana, b, archive(1), restore(1), archive(9), restore(9))
            got = changed(live)
            assert [(e.bench_id, e.seq) for e in got] == [(b, 2), (b, 3)]
            assert all(e.shown == Shown(w.alana.household_id, w.alana.person_id) for e in got)

    run(scenario())


def test_logs_name_archive_and_restore_by_type_and_never_carry_a_title_or_body(
        db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    w = world(db_url)
    capsys.readouterr()

    async def scenario() -> int:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, add("PLNT", "PLNT-BODY"), archive(1), restore(1), restore(1),
                               archive(7))
            await s.close(w.alana, b)
            await s.reopen(w.alana, b)
            return b

    b = asyncio.run(scenario())
    out = capsys.readouterr().out
    assert "PLNT" not in out
    cmds = events(out, "workshop.command")
    assert [(c["type"], c["outcome"], c["bench"]) for c in cmds][1:] == [
        ("archive", "accepted", str(b)), ("restore", "accepted", str(b)), ("restore", "no_such_piece", str(b)),
        ("archive", "no_such_piece", str(b))]
    assert [e["bench"] for e in events(out, "workshop.reopened")] == [str(b)]


# --- a shelved piece through the service ---------------------------------------------------------------------------------


def test_a_shelved_piece_takes_no_edit_move_or_remove_through_the_service(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3, archive(2))
            got = await do(s, w.alana, b, edit(2, 1), move(2, 0), remove(2), archive(2))
            assert [g.outcome for g in got] == ["no_such_piece"] * 4
            assert ids((await s.read(w.alana, b)).shelf) == [2]

    run(scenario())


def test_her_archive_is_hers_in_the_log_and_a_person_can_undo_it(db_url: str) -> None:
    w = world(db_url)
    from ashley.workshop.model import HER

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            applied = await s.apply(w.alana, b, archive(2, HER))
            assert applied.outcome == "accepted"
            rows = await s.log(w.alana, b)
            assert rows[-1].by == HER and rows[-1].by.author == "ashley"
            assert (await do(s, w.alana, b, undo(applied.seq)))[0].outcome == "accepted"
            assert ids((await s.read(w.alana, b)).pieces) == [1, 2, 3]

    run(scenario())


def test_another_person_cannot_archive_on_a_bench_that_is_not_theirs(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            for other in (w.sam, w.zed):
                with pytest.raises(BenchNotFound):
                    await s.apply(other, b, archive(1, by(other)))
                with pytest.raises(BenchNotFound):
                    await s.apply(other, b, restore(1, by(other)))
            assert (await s.read(w.alana, b)).shelf == () and len(await s.log(w.alana, b)) == 3

    run(scenario())


def test_an_archive_naming_another_person_is_refused_before_the_database(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        async with workshop(db_url) as s:
            b = await bench_of(s, w.alana, *A3)
            with pytest.raises(ValueError):
                await s.apply(w.alana, b, archive(1, by(w.sam)))
            assert len(await s.log(w.alana, b)) == 3

    run(scenario())
