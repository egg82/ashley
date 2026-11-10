"""`Workshop.unseen`, `reaction_ages` and `reacted` over a real database: what counts as the person's change, the
pause, the mark, the limits and the keeping window."""

import pytest
from ashley.workshop.commands import Archive, Edit, Move, Remove, Rename, Undo
from ashley.workshop.model import HER, By, Place, Text
from bench_reacts_blind_support import PAUSE, SENTINEL, world
from contract.conversations_support import run

OLD = PAUSE * 10


def test_a_person_change_quiet_for_the_pause_is_unseen_with_ids_and_kinds_only(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            seq = await w.person_adds(bench, kind="document")
            w.quiet(OLD)
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            assert (got.bench_id, got.household_id, got.owner_id) == (bench, w.home.id, w.home.person)
            assert (got.after, got.to_seq, got.count) == (0, seq, 1)
            [done] = got.done
            assert (done.seq, done.type, done.kind) == (seq, "add", "document") and done.piece_id is not None
            assert SENTINEL not in repr(got)
    run(go())


def test_nothing_is_unseen_before_the_pause_and_it_is_at_the_pause(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
            w.quiet(PAUSE - 5)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
            w.quiet(PAUSE)
            assert len(await w.workshop.unseen(PAUSE, 10, 10)) == 1
            w.quiet(PAUSE + 5)
            assert len(await w.workshop.unseen(PAUSE, 10, 10)) == 1
    run(go())


def test_the_pause_is_the_argument_not_a_constant(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet(100)
            assert await w.workshop.unseen(200, 10, 10) == ()
            assert len(await w.workshop.unseen(90, 10, 10)) == 1
    run(go())


def test_a_new_edit_during_the_pause_resets_it_for_every_change_before_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            w.quiet(OLD)
            assert len(await w.workshop.unseen(PAUSE, 10, 10)) == 1
            edit = await w.person_edits(bench, piece, 1)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
            w.age_commands(bench, OLD)
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            assert got.count == 2 and got.to_seq == edit and [d.seq for d in got.done] == [piece, edit]
    run(go())


def test_her_commands_never_make_a_bench_unseen(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.she_adds(bench)
            w.quiet(OLD)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
    run(go())


def test_her_recent_command_neither_resets_the_pause_nor_is_listed(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            mine = await w.person_adds(bench)
            w.quiet(OLD)
            await w.she_adds(bench)
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            assert got.to_seq == mine and got.count == 1 and [d.seq for d in got.done] == [mine]
    run(go())


def test_her_undo_and_her_other_kinds_of_command_never_count(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.she_adds(bench)
            view = await w.workshop.read(w.home.owner, bench)
            [piece] = view.pieces
            for command in (Edit(HER, piece.id, piece.version, Text("Note", "again")),
                            Move(HER, piece.id, Place(0, "large")), Rename(HER, "renamed")):
                last = await w.workshop.apply(w.home.owner, bench, command)
                assert last.outcome == "accepted", command
            assert (await w.workshop.apply(w.home.owner, bench, Undo(HER, last.seq))).outcome == "accepted"
            w.quiet(OLD)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
    run(go())


def test_a_person_undo_is_a_change_of_theirs(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            seq = await w.person_adds(bench)
            before = await w.workshop.apply(w.home.owner, bench, Undo(By(w.home.person), seq))
            assert before.outcome == "accepted"
            w.quiet(OLD)
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            assert got.count == 2 and got.done[-1].type == "undo"
    run(go())


def test_a_refused_command_is_not_a_change_and_does_not_reset_the_pause(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            w.quiet(OLD)
            stale = await w.workshop.apply(w.home.owner, bench, Edit(By(w.home.person), piece, 99, Text("x", "y")))
            assert stale.outcome != "accepted"
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            assert got.count == 1 and got.to_seq == piece
    run(go())


def test_a_bench_with_only_a_refused_command_has_nothing_unseen(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            refused = await w.workshop.apply(w.home.owner, bench, Remove(By(w.home.person), 12345))
            assert refused.outcome != "accepted"
            w.quiet(OLD)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
    run(go())


def test_a_closed_bench_is_never_unseen_and_is_again_once_reopened(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench)
            w.quiet(OLD)
            await w.workshop.close(w.home.owner, bench)
            w.quiet(OLD)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
            await w.workshop.reopen(w.home.owner, bench)
            w.quiet(OLD)
            assert [u.bench_id for u in await w.workshop.unseen(PAUSE, 10, 10)] == [bench]
    run(go())


def test_each_household_sees_its_own_benches_with_its_own_ids(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, households=2) as w:
            a, b = w.homes
            ba, bb = await w.bench(a), await w.bench(b)
            await w.person_adds(ba, home=a)
            await w.person_adds(bb, home=b)
            w.quiet(OLD)
            got = {u.bench_id: u for u in await w.workshop.unseen(PAUSE, 10, 10)}
            assert set(got) == {ba, bb}
            assert (got[ba].household_id, got[ba].owner_id) == (a.id, a.person)
            assert (got[bb].household_id, got[bb].owner_id) == (b.id, b.person)
    run(go())


def test_recording_a_reaction_against_another_households_bench_marks_nothing(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url, households=2) as w:
            a, b = w.homes
            bb = await w.bench(b)
            seq = await w.person_adds(bb, home=b)
            w.quiet(OLD)
            with pytest.raises(Exception):
                await w.workshop.reacted(a.id, bb, seq, 1e6)
            assert [u.bench_id for u in await w.workshop.unseen(PAUSE, 10, 10)] == [bb]
            assert w.reaction_rows(bb) == []
    run(go())


def test_reacted_moves_the_mark_so_the_next_unseen_starts_after_it(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            w.quiet(OLD)
            [first] = await w.workshop.unseen(PAUSE, 10, 10)
            await w.workshop.reacted(first.household_id, bench, first.to_seq, 1e6)
            assert await w.workshop.unseen(PAUSE, 10, 10) == ()
            edit = await w.person_edits(bench, piece, 1)
            w.quiet(OLD)
            [second] = await w.workshop.unseen(PAUSE, 10, 10)
            assert (second.after, second.to_seq, second.count) == (piece, edit, 1)
            assert [d.seq for d in second.done] == [edit]
    run(go())


def test_a_partial_mark_leaves_the_later_changes_unseen(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            e1 = await w.person_edits(bench, piece, 1)
            e2 = await w.person_edits(bench, piece, 2)
            w.quiet(OLD)
            await w.workshop.reacted(w.home.id, bench, e1, 1e6)
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            assert (got.after, got.to_seq, got.count) == (e1, e2, 1)
    run(go())


def test_recording_the_same_mark_twice_changes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            seq = await w.person_adds(bench)
            await w.workshop.reacted(w.home.id, bench, seq, 1e6)
            await w.workshop.reacted(w.home.id, bench, seq, 1e6)
            assert w.reaction_rows(bench) == [seq]
            assert len(await w.workshop.reaction_ages(bench, 1e6)) == 1
    run(go())


def test_the_mark_is_per_bench(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            one, two = await w.bench(), await w.bench(title="other")
            s1, s2 = await w.person_adds(one), await w.person_adds(two)
            w.quiet(OLD)
            await w.workshop.reacted(w.home.id, one, s1, 1e6)
            assert [u.bench_id for u in await w.workshop.unseen(PAUSE, 10, 10)] == [two]
            assert s2 > 0
    run(go())


def test_limit_caps_the_benches_and_the_longest_quiet_come_first(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            benches = [await w.bench(title=f"b{n}") for n in range(3)]
            for b in benches:
                await w.person_adds(b)
            for b, age in zip(benches, (OLD, OLD * 3, OLD * 2)):
                w.age_commands(b, age)
            got = await w.workshop.unseen(PAUSE, 2, 10)
            assert [u.bench_id for u in got] == [benches[1], benches[2]]
            assert [u.bench_id for u in await w.workshop.unseen(PAUSE, 10, 10)] == [benches[1], benches[2], benches[0]]
    run(go())


def test_listed_keeps_the_latest_commands_oldest_first_and_count_is_all_of_them(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            seqs = [piece] + [await w.person_edits(bench, piece, v) for v in range(1, 5)]
            w.quiet(OLD)
            [got] = await w.workshop.unseen(PAUSE, 10, 2)
            assert got.count == 5 and got.to_seq == seqs[-1]
            assert [d.seq for d in got.done] == seqs[-2:]
    run(go())


def test_a_command_with_no_piece_has_no_piece_id_or_kind_and_a_removed_piece_has_no_kind(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.person_adds(bench)
            view = await w.workshop.read(w.home.owner, bench)
            pid = view.pieces[0].id
            by = By(w.home.person)
            assert (await w.workshop.apply(w.home.owner, bench, Rename(by, "new name"))).outcome == "accepted"
            assert (await w.workshop.apply(w.home.owner, bench, Remove(by, pid))).outcome == "accepted"
            w.quiet(OLD)
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            by_type = {d.type: d for d in got.done}
            assert by_type["rename"].piece_id is None and by_type["rename"].kind is None
            assert by_type["remove"].piece_id == pid and by_type["remove"].kind is None
            assert by_type["add"].seq == piece
    run(go())


def test_a_piece_archived_by_the_person_is_listed_with_its_kind(db_url: str) -> None:
    async def go() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            await w.person_adds(bench, kind="code")
            pid = (await w.workshop.read(w.home.owner, bench)).pieces[0].id
            assert (await w.workshop.apply(w.home.owner, bench, Archive(By(w.home.person), pid))).outcome == "accepted"
            w.quiet(OLD)
            [got] = await w.workshop.unseen(PAUSE, 10, 10)
            assert got.done[-1].type == "archive" and got.done[-1].kind == "code"
    run(go())
