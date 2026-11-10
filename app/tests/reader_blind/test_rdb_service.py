"""The Postgres Workshop with reader pieces and points: the latest accepted point of each piece in `BenchView.pointers`
(from the log), the log and Live as for any change, nothing stored twice, no reaction of hers to a person's point."""

from ashley.live.events import BenchChanged
from ashley.workshop.commands import Add, Archive, Point, Pointed, Remove, Undo
from ashley.workshop.model import HER, Text
from ashley.workshop.reader import Passage
from ashley.workshop.workshop import Pointer
from contract.conversations_support import run, scalar
from reader_blind_support import TEXT, add_note, add_reader, edit_text, env, opened, person_by, point, put, reader_on

P = Passage(0, 4, 9)
Q = Passage(1, 0, 6)
PAUSE = 60.0


def quiet(url: str, seconds: float) -> None:
    scalar(url, "WITH u AS (UPDATE bench_commands SET at = clock_timestamp() - make_interval(secs => %s) "
                "RETURNING 1) SELECT count(*) FROM u", (seconds,))


def test_a_point_is_applied_logged_and_announced_like_a_change(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            before = len([x for x in e.live.published if isinstance(x, BenchChanged)])
            done = await e.workshop.apply(a, bench, Point(HER, piece, 1, P))
            assert (done.seq, done.outcome, done.piece_id, done.effect) == (2, "accepted", piece, Pointed(piece, 1, P))
            rows = await e.workshop.log(a, bench)
            assert rows[-1].command == Point(HER, piece, 1, P) and rows[-1].outcome == "accepted"
            assert rows[-1].piece_id == piece and rows[-1].by.author == "ashley"
            sent = [x for x in e.live.published if isinstance(x, BenchChanged)]
            assert len(sent) == before + 1 and (sent[-1].bench_id, sent[-1].seq) == (bench, 2)

    run(go())


def test_a_read_serves_the_pointer_with_its_seq_version_and_passage(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            assert (await e.workshop.read(a, bench)).pointers == {}
            seq = await put(e, a, bench, point(piece, 1, P))
            assert (await e.workshop.read(a, bench)).pointers == {piece: Pointer(seq, 1, P)}

    run(go())


def test_the_latest_accepted_point_of_a_piece_is_the_one_served(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            await put(e, a, bench, point(piece, 1, P))
            second = await put(e, a, bench, point(piece, 1, Q))
            assert (await e.workshop.read(a, bench)).pointers == {piece: Pointer(second, 1, Q)}

    run(go())


def test_a_refused_point_does_not_replace_the_pointer(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            first = await put(e, a, bench, point(piece, 1, P))
            for bad in (point(piece, 1, Passage(0, 3, 3)), point(piece, 9, Q)):
                assert (await e.workshop.apply(a, bench, bad)).outcome in ("bad_passage", "stale_base")
            assert (await e.workshop.read(a, bench)).pointers == {piece: Pointer(first, 1, P)}

    run(go())


def test_a_point_with_no_passage_takes_the_pointer_away(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            await put(e, a, bench, point(piece, 1, P))
            await put(e, a, bench, point(piece, 1, None))
            assert (await e.workshop.read(a, bench)).pointers == {}
            again = await put(e, a, bench, point(piece, 1, Q))
            assert (await e.workshop.read(a, bench)).pointers == {piece: Pointer(again, 1, Q)}

    run(go())


def test_each_reader_piece_has_its_own_pointer(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            one = await reader_on(e, a, bench)
            two = await reader_on(e, a, bench, "other words entirely")
            s1 = await put(e, a, bench, point(one, 1, P))
            s2 = await put(e, a, bench, point(two, 1, Passage(0, 0, 5)))
            await put(e, a, bench, point(one, 1, None))
            assert (await e.workshop.read(a, bench)).pointers == {two: Pointer(s2, 1, Passage(0, 0, 5))}
            assert s1 < s2

    run(go())


def test_the_pointer_keeps_the_version_it_was_made_against_after_the_piece_changes(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            seq = await put(e, a, bench, point(piece, 1, P))
            await put(e, a, bench, edit_text(piece, 1, "completely different text", person_by(a)))
            view = await e.workshop.read(a, bench)
            assert view.pointers == {piece: Pointer(seq, 1, P)}
            [shown] = [p for p in view.pieces if p.id == piece]
            assert shown.version == 2

    run(go())


def test_a_point_changes_no_piece_and_the_benchs_last_change_does_not_move(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            note = await put(e, a, bench, add_note(by=person_by(a)))
            before = await e.workshop.read(a, bench)
            await put(e, a, bench, point(piece, 1, P))
            after = await e.workshop.read(a, bench)
            assert after.pieces == before.pieces and after.changes == before.changes
            [reader] = [p for p in after.pieces if p.id == piece]
            assert (reader.version, reader.changed_by) == (1, piece) and note > piece

    run(go())


def test_the_pointer_is_derived_from_the_log_so_a_fresh_read_agrees(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            seq = await put(e, a, bench, point(piece, 1, P))
        async with env(db_url) as fresh:
            assert (await fresh.workshop.read(a, bench)).pointers == {piece: Pointer(seq, 1, P)}

    run(go())


def test_a_point_is_never_undone_and_the_undo_walk_passes_over_it(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            edit = await put(e, a, bench, edit_text(piece, 1, "later words", person_by(a)))
            pointed = await put(e, a, bench, point(piece, 2, Passage(0, 0, 5)))
            view = await e.workshop.read(a, bench)
            assert view.undo_next == edit
            assert (await e.workshop.apply(a, bench, Undo(person_by(a), pointed))).outcome == "nothing_to_undo"
            assert (await e.workshop.apply(a, bench, Undo(person_by(a), edit))).outcome == "accepted"

    run(go())


def test_undo_next_with_only_a_point_after_the_add_is_the_add(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            await put(e, a, bench, point(piece, 1, P))
            assert (await e.workshop.read(a, bench)).undo_next == piece

    run(go())


def test_a_point_by_a_person_is_logged_as_theirs(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            await put(e, a, bench, point(piece, 1, None, by=person_by(a)))
            [row] = [r for r in await e.workshop.log(a, bench) if isinstance(r.command, Point)]
            assert row.by.author == "person" and row.by.person_id == a.person_id

    run(go())


def test_another_household_cannot_point_on_the_bench(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            try:
                await e.workshop.apply(e.world.zed, bench, point(piece, 1, P))
            except Exception as raised:
                assert type(raised).__name__ == "BenchNotFound"
            else:
                raise AssertionError("a stranger pointed on a bench that is not theirs")
            assert (await e.workshop.read(a, bench)).pointers == {}

    run(go())


# --- no reaction to a person's point ----------------------------------------------------------------------------------


def test_a_person_point_is_not_a_change_she_reacts_to(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            quiet(db_url, PAUSE * 10)
            [seen] = await e.workshop.unseen(PAUSE, 10, 10)
            await e.workshop.reacted(a.household_id, bench, seen.to_seq, 1e6)
            assert await e.workshop.unseen(PAUSE, 10, 10) == ()
            await put(e, a, bench, point(piece, 1, P, by=person_by(a)))
            await put(e, a, bench, point(piece, 1, None, by=person_by(a)))
            quiet(db_url, PAUSE * 10)
            assert await e.workshop.unseen(PAUSE, 10, 10) == ()

    run(go())


def test_a_person_edit_after_the_points_is_still_a_change_she_reacts_to(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            quiet(db_url, PAUSE * 10)
            [seen] = await e.workshop.unseen(PAUSE, 10, 10)
            await e.workshop.reacted(a.household_id, bench, seen.to_seq, 1e6)
            await put(e, a, bench, point(piece, 1, P, by=person_by(a)))
            edit = await put(e, a, bench, edit_text(piece, 1, "new words", person_by(a)))
            quiet(db_url, PAUSE * 10)
            [got] = await e.workshop.unseen(PAUSE, 10, 10)
            assert got.to_seq == edit and got.count == 1 and [d.seq for d in got.done] == [edit]

    run(go())


def test_her_point_never_makes_a_bench_unseen_either(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            quiet(db_url, PAUSE * 10)
            [seen] = await e.workshop.unseen(PAUSE, 10, 10)
            await e.workshop.reacted(a.household_id, bench, seen.to_seq, 1e6)
            await put(e, a, bench, point(piece, 1, P, by=HER))
            quiet(db_url, PAUSE * 10)
            assert await e.workshop.unseen(PAUSE, 10, 10) == ()

    run(go())


def test_a_reader_piece_survives_archive_and_restore_with_its_body(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            await put(e, a, bench, Archive(person_by(a), piece))
            view = await e.workshop.read(a, bench)
            assert [p.text.body for p in view.shelf] == [add_reader(TEXT).text.body]

    run(go())


def test_pointing_on_removed_or_missing_pieces_is_refused_and_leaves_no_pointer(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            await put(e, a, bench, Remove(person_by(a), piece))
            assert (await e.workshop.apply(a, bench, point(piece, 1, P))).outcome == "no_such_piece"
            assert (await e.workshop.read(a, bench)).pointers == {}

    run(go())


def test_a_bad_reader_body_is_refused_by_the_service_too(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            done = await e.workshop.apply(a, bench, Add(person_by(a), "reader", Text("r", "not a page"), "small"))
            assert (done.outcome, done.piece_id) == ("bad_reader", None)

    run(go())



def test_a_point_does_not_move_the_benchs_last_change_but_an_edit_does(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await reader_on(e, a, bench)
            [listed] = [b for b in await e.workshop.open_benches(a) if b.id == bench]
            first = listed.last_changed_at
            assert first is not None
            quiet(db_url, 1000)
            await put(e, a, bench, point(piece, 1, P))
            await put(e, a, bench, point(piece, 1, None, by=person_by(a)))
            [after] = [b for b in await e.workshop.open_benches(a) if b.id == bench]
            assert after.last_changed_at is not None and after.last_changed_at < first
            await put(e, a, bench, edit_text(piece, 1, "other", person_by(a)))
            [edited] = [b for b in await e.workshop.open_benches(a) if b.id == bench]
            assert edited.last_changed_at is not None and edited.last_changed_at > after.last_changed_at

    run(go())
