"""Her bench tools with reader pieces on a real Postgres Workshop: a reader put up by the result number of a page read
this turn (`bench_add`, `bench_edit`), the whole text kept up to the kind's limit, `bench_replace` refused, `bench_point`
resolving a quote, and `bench_read_piece` paging the page's text."""

from ashley.tools.bench_tools import BenchTools
from ashley.tools.results import ReadPage, Results
from ashley.workshop.model import HER
from ashley.workshop.reader import body_of, page_of
from contract.conversations_support import run
from reader_blind_support import (KIND_MAX, LONG, PAGE_URL, add_note, added, call, env, js, opened, person_by,
                                  properties_of, put, rig, stored, tools)


def test_the_catalogue_offers_bench_point_and_result_on_add_and_edit() -> None:
    async def go() -> None:
        specs = {s.name: s for s in (await BenchTools(1, 1, 1).catalogue()).specs}
        point = specs["bench_point"]
        assert point.parameters["required"] == ["piece_id", "quote"] and not point.reads
        for name in ("bench_add", "bench_edit"):
            assert "result" in properties_of(specs[name].parameters)
        assert "reader" in properties_of(specs["bench_add"].parameters)["kind"]["enum"]

    run(go())


# --- by result --------------------------------------------------------------------------------------------------------


def test_a_reader_is_put_up_by_the_result_of_a_page_read_and_holds_its_url_title_and_text(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            assert await stored(e, bench, piece) == body_of(PAGE_URL, "Page title", "alpha one\nbeta two three\ngamma four")
            [view] = [p for p in (await e.workshop.read(e.world.alana, bench)).pieces]
            assert (view.kind, view.text.title, view.version) == ("reader", "Reading", 1)
            rows = await e.workshop.log(e.world.alana, bench)
            assert rows[-1].by == HER and rows[-1].outcome == "accepted"

    run(go())


def test_the_piece_holds_the_pages_whole_text_not_the_part_she_was_given(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            text = "\n".join(f"paragraph {i} " + "w" * 90 for i in range(300))
            assert len(text) > 20000
            t, store, n = rig(e, bench, text)
            piece = await added(e, bench, t, store, n)
            page = page_of(await stored(e, bench, piece))
            assert page is not None and page.text == text

    run(go())


def test_a_page_over_the_kind_limit_is_cut_at_the_end_to_fit(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            text = "\n".join(f"line {i:06d} " + "x" * 40 for i in range(6000))
            assert len(text) > KIND_MAX + 1000
            t, store, n = rig(e, bench, text)
            piece = await added(e, bench, t, store, n)
            body = await stored(e, bench, piece)
            page = page_of(body)
            assert page is not None and len(body) <= KIND_MAX and len(body) >= KIND_MAX - 200
            assert text.startswith(page.text) and 0 < len(page.text) < len(text)
            assert (page.url, page.title) == (PAGE_URL, "Page title")

    run(go())


def test_a_cut_page_that_needs_escaping_still_fits_the_limit(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            text = "\n".join(["\"q\" \\ é" for _ in range(60000)])
            t, store, n = rig(e, bench, text, title="T \"quoted\"")
            piece = await added(e, bench, t, store, n)
            body = await stored(e, bench, piece)
            page = page_of(body)
            assert page is not None and len(body) <= KIND_MAX and text.startswith(page.text)
            assert len(page.text) > KIND_MAX // 4

    run(go())


def test_a_page_just_within_the_limit_is_not_cut(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            text = "y" * (KIND_MAX - len(body_of(PAGE_URL, "T", "")))
            t, store, n = rig(e, bench, text, title="T")
            piece = await added(e, bench, t, store, n)
            page = page_of(await stored(e, bench, piece))
            assert page is not None and page.text == text

    run(go())


def test_a_result_whose_page_was_not_read_is_unread_page_and_nothing_is_added(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, _ = rig(e, bench)
            other = store.record("https://example.org/not-read")
            got = await call(t, store, "bench_add", kind="reader", title="x", result=other)
            assert got.is_error and got.content.startswith("unread_page")
            assert (await e.workshop.read(e.world.alana, bench)).pieces == ()

    run(go())


def test_a_number_no_result_has_is_unknown_result(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            for number in (n + 5, 0, 99):
                got = await call(t, store, "bench_add", kind="reader", title="x", result=number)
                assert got.is_error and got.content.startswith("unknown_result"), number
            assert (await e.workshop.read(e.world.alana, bench)).pieces == ()

    run(go())


def test_a_body_she_types_is_bad_arguments_with_or_without_a_result(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            typed = body_of(PAGE_URL, "T", "typed text")
            for args in ({"body": typed}, {"body": typed, "result": n}, {"body": "words"}):
                got = await call(t, store, "bench_add", kind="reader", title="x", **args)
                assert got.is_error and got.content.startswith("bad_arguments"), args
            assert (await e.workshop.read(e.world.alana, bench)).pieces == ()

    run(go())


def test_a_reader_with_neither_result_nor_body_is_not_added(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, _ = rig(e, bench)
            got = await call(t, store, "bench_add", kind="reader", title="x")
            assert got.is_error
            assert (await e.workshop.read(e.world.alana, bench)).pieces == ()

    run(go())


def test_a_page_kept_in_another_turns_results_is_not_read_in_this_turn(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            _, _, n = rig(e, bench)
            fresh = Results()
            t = tools(e.world.alana, bench, fresh)
            got = await call(t, fresh, "bench_add", kind="reader", title="x", result=n)
            assert got.is_error and got.content.startswith("unknown_result")

    run(go())


def test_edit_by_result_replaces_the_page_and_raises_the_version(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            second = store.record("https://example.org/second")
            store.keep(second, ReadPage("Second", "new text\nmore"))
            assert not (await call(t, store, "bench_read_piece", piece_id=piece)).is_error
            got = await call(t, store, "bench_edit", piece_id=piece, base_version=1, title="Reading 2", result=second)
            assert not got.is_error, got.content
            assert await stored(e, bench, piece) == body_of("https://example.org/second", "Second", "new text\nmore")
            [view] = (await e.workshop.read(e.world.alana, bench)).pieces
            assert (view.version, view.text.title) == (2, "Reading 2")

    run(go())


def test_edit_by_an_unread_or_unknown_result_changes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            before = await stored(e, bench, piece)
            unread = store.record("https://example.org/unread")
            await call(t, store, "bench_read_piece", piece_id=piece)
            a = await call(t, store, "bench_edit", piece_id=piece, base_version=1, title="x", result=unread)
            b = await call(t, store, "bench_edit", piece_id=piece, base_version=1, title="x", result=unread + 40)
            assert a.is_error and a.content.startswith("unread_page")
            assert b.is_error and b.content.startswith("unknown_result")
            assert await stored(e, bench, piece) == before

    run(go())


def test_edit_of_a_reader_with_a_typed_body_is_bad_arguments(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            before = await stored(e, bench, piece)
            await call(t, store, "bench_read_piece", piece_id=piece)
            got = await call(t, store, "bench_edit", piece_id=piece, base_version=1, title="x", body=body_of(PAGE_URL, "T", "z"))
            assert got.is_error and got.content.startswith("bad_arguments")
            assert await stored(e, bench, piece) == before

    run(go())


def test_bench_replace_on_a_reader_is_refused_and_changes_nothing(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            before = await stored(e, bench, piece)
            await call(t, store, "bench_read_piece", piece_id=piece)
            got = await call(t, store, "bench_replace", piece_id=piece, base_version=1, old="beta two", new="BETA")
            assert got.is_error
            assert await stored(e, bench, piece) == before
            assert [r.outcome for r in await e.workshop.log(e.world.alana, bench)] == ["accepted"]

    run(go())


# --- bench_read_piece -------------------------------------------------------------------------------------------------


def test_reading_a_reader_gives_the_page_text_as_the_body_with_its_url_and_title(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            got = js(await call(t, store, "bench_read_piece", piece_id=piece))
            assert got["body"] == "alpha one\nbeta two three\ngamma four"
            assert (got["url"], got["page_title"], got["version"], got["kind"]) == (PAGE_URL, "Page title", 1, "reader")
            assert got["body_cut"] is False and got["offset"] == 0

    run(go())


def test_a_long_page_is_paged_by_offset_and_the_windows_join_to_the_text(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench, LONG)
            piece = await added(e, bench, t, store, n)
            joined, offset, windows = "", 0, 0
            while True:
                got = js(await call(t, store, "bench_read_piece", piece_id=piece, offset=offset))
                assert got["offset"] == offset and got["body"]
                joined += got["body"]
                offset += len(got["body"])
                windows += 1
                assert (got["url"], got["page_title"]) == (PAGE_URL, "Page title")
                if not got["body_cut"]:
                    break
                assert windows < 100
            assert windows > 1 and joined == LONG

    run(go())


def test_reading_a_reader_at_an_offset_starts_inside_the_text(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t, store, n = rig(e, bench)
            piece = await added(e, bench, t, store, n)
            got = js(await call(t, store, "bench_read_piece", piece_id=piece, offset=10))
            assert got["body"] == "beta two three\ngamma four" and got["offset"] == 10

    run(go())


def test_reading_a_note_has_no_url_or_page_title(db_url: str) -> None:
    async def go() -> None:
        async with env(db_url) as e:
            a = e.world.alana
            bench = await opened(e, a)
            piece = await put(e, a, bench, add_note(by=person_by(a)))
            got = js(await call(tools(a, bench), None, "bench_read_piece", piece_id=piece))
            assert "page_title" not in got

    run(go())


