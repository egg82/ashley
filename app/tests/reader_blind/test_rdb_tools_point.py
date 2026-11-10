"""`bench_point` on a real Postgres Workshop: a quote resolved into a pointer in code points, refusals, clearing, the
current version, and that her point is never undone."""

from ashley.live.events import BenchChanged
from ashley.tools.results import ReadPage
from ashley.workshop.commands import Point
from ashley.workshop.model import HER
from ashley.workshop.reader import Passage
from ashley.workshop.workshop import Pointer
from contract.conversations_support import run
from reader_blind_support import add_note, added, call, env, find, js, opened, person_by, put, rig, tools


def test_bench_point_resolves_the_quote_into_a_pointer_logged_as_hers_and_announced(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            sent = len([x for x in e.live.published if isinstance(x, BenchChanged)])
            got = await call(t, store, "bench_point", piece_id=piece, quote="two three")
            assert not got.is_error, got.content
            seq = int(js(got)["seq"])
            view = await e.workshop.read(a, bench)
            assert view.pointers == {piece: Pointer(seq, 1, Passage(1, 5, 14))}
            rows = await e.workshop.log(a, bench)
            assert rows[-1].command == Point(HER, piece, 1, Passage(1, 5, 14)) and rows[-1].seq == seq
            assert len([x for x in e.live.published if isinstance(x, BenchChanged)]) == sent + 1

    run(go())


def test_bench_point_counts_code_points(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench, "😀😀 target café tail")
            piece = await added(e, bench, t, store, n)
            assert not (await call(t, store, "bench_point", piece_id=piece, quote="target")).is_error
            [pointer] = (await e.workshop.read(a, bench)).pointers.values()
            assert pointer.passage == Passage(0, 3, 9)
            assert not (await call(t, store, "bench_point", piece_id=piece, quote="tail")).is_error
            [pointer] = (await e.workshop.read(a, bench)).pointers.values()
            assert pointer.passage == Passage(0, 16, 20)

    run(go())


def test_bench_point_with_a_repeated_missing_or_multi_line_quote_is_bad_arguments(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench, "again and again\nsecond line\nagain")
            piece = await added(e, bench, t, store, n)
            for quote in ("again", "not on the page", "again\nsecond", "line\nagain", "\n"):
                got = await call(t, store, "bench_point", piece_id=piece, quote=quote)
                assert got.is_error and got.content.startswith("bad_arguments"), quote
            got = await call(t, store, "bench_point", piece_id=piece)
            assert got.is_error and got.content.startswith("bad_arguments")
            assert (await e.workshop.read(a, bench)).pointers == {}
            assert [r.outcome for r in await e.workshop.log(a, bench)] == ["accepted"]

    run(go())


def test_bench_point_with_a_quote_that_is_not_a_string_is_bad_arguments(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            for quote in (5, None, ["alpha"]):
                got = await call(t, store, "bench_point", piece_id=piece, quote=quote)
                assert got.is_error and got.content.startswith("bad_arguments"), quote

    run(go())


def test_bench_point_at_another_kind_is_not_reader(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await put(e, a, bench, add_note("n", "some words", by=person_by(a)))
            got = await call(tools(a, bench), None, "bench_point", piece_id=piece, quote="words")
            assert got.is_error and got.content.startswith("not_reader")
            cleared = await call(tools(a, bench), None, "bench_point", piece_id=piece, quote="")
            assert cleared.is_error and cleared.content.startswith("not_reader")

    run(go())


def test_bench_point_at_a_piece_that_is_not_there_is_no_such_piece(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            got = await call(tools(a, bench), None, "bench_point", piece_id=42, quote="x")
            assert got.is_error and got.content.startswith("no_such_piece")

    run(go())


def test_an_empty_quote_takes_the_highlight_away_and_is_a_clearing_point(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            await call(t, store, "bench_point", piece_id=piece, quote="alpha")
            got = await call(t, store, "bench_point", piece_id=piece, quote="")
            assert not got.is_error, got.content
            assert (await e.workshop.read(a, bench)).pointers == {}
            assert (await e.workshop.log(a, bench))[-1].command == Point(HER, piece, 1, None)
            again = await call(t, store, "bench_point", piece_id=piece, quote="")
            assert not again.is_error

    run(go())


def test_a_second_point_moves_the_highlight(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            await call(t, store, "bench_point", piece_id=piece, quote="alpha")
            second = js(await call(t, store, "bench_point", piece_id=piece, quote="gamma"))
            [pointer] = (await e.workshop.read(a, bench)).pointers.values()
            assert pointer.passage == Passage(2, 0, 5) and pointer.seq == second["seq"]

    run(go())


def test_bench_point_uses_the_pieces_current_version(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            other = store.record("https://example.org/two")
            store.keep(other, ReadPage("Two", "fresh words\nhere"))
            await call(t, store, "bench_read_piece", piece_id=piece)
            await call(t, store, "bench_edit", piece_id=piece, base_version=1, title="r", result=other)
            got = await call(t, store, "bench_point", piece_id=piece, quote="fresh")
            assert not got.is_error, got.content
            [pointer] = (await e.workshop.read(a, bench)).pointers.values()
            assert (pointer.version, pointer.passage) == (2, Passage(0, 0, 5))
            stale = await call(t, store, "bench_point", piece_id=piece, quote="alpha")
            assert stale.is_error

    run(go())


def test_her_point_is_never_undone_by_bench_undo(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            seq = int(js(await call(t, store, "bench_point", piece_id=piece, quote="alpha"))["seq"])
            got = await call(t, store, "bench_undo", seq=seq)
            assert got.is_error and "nothing_to_undo" in got.content
            read = js(await call(t, store, "bench_read"))
            assert read["undo_next"] == piece
            assert find(read, "type").count("point") == 1

    run(go())


