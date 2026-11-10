"""Her shelf tools: `bench_archive` and `bench_restore` build the person's Commands by her and go through
`Workshop.apply`; `bench_shelf` reads the shelf; `bench_read` counts what is `shelved`."""

from ashley.live.events import BenchChanged
from ashley.workshop.commands import Archive, Restore
from ashley.workshop.model import HER
from contract.conversations_support import run
from tools_support import Env, call, env, js, opened, person_add, pieces_with_title, put, tools, values_of

LIMIT = 50


async def three(e: Env) -> tuple[int, list[int]]:
    bench = await opened(e, e.world.alana)
    ids = [await put(e, e.world.alana, bench, person_add(e.world.alana, t, t.upper())) for t in ("one", "two", "thr")]
    assert None not in ids
    return bench, [i for i in ids if i is not None]


def test_the_catalogue_offers_the_three_shelf_tools_with_a_piece_id() -> None:
    async def scenario() -> None:
        from ashley.tools.bench_tools import BenchTools

        specs = {s.name: s for s in (await BenchTools(1, 1, 1).catalogue()).specs}
        for name in ("bench_archive", "bench_restore"):
            assert specs[name].parameters["required"] == ["piece_id"] and not specs[name].reads
        assert specs["bench_shelf"].reads and specs["bench_shelf"].parameters["required"] == []

    run(scenario())


def test_archive_builds_her_archive_logs_it_as_hers_and_announces_it(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            result = await tools(e, bench).call(call("bench_archive", piece_id=ids[1]))
            assert not result.is_error
            rows = await e.workshop.log(e.world.alana, bench)
            assert rows[-1].command == Archive(HER, ids[1]) and rows[-1].outcome == "accepted"
            assert rows[-1].by.author == "ashley" and rows[-1].piece_id == ids[1]
            view = await e.workshop.read(e.world.alana, bench)
            assert [p.id for p in view.pieces] == [ids[0], ids[2]] and [p.id for p in view.shelf] == [ids[1]]
            sent = [x for x in e.live.published if isinstance(x, BenchChanged)]
            assert sent[-1].bench_id == bench and sent[-1].seq == 4

    run(scenario())


def test_restore_builds_her_restore_and_puts_the_piece_last(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            await t.call(call("bench_archive", piece_id=ids[0]))
            result = await t.call(call("bench_restore", piece_id=ids[0]))
            assert not result.is_error
            rows = await e.workshop.log(e.world.alana, bench)
            assert rows[-1].command == Restore(HER, ids[0]) and rows[-1].outcome == "accepted"
            view = await e.workshop.read(e.world.alana, bench)
            assert [p.id for p in view.pieces] == [ids[1], ids[2], ids[0]] and view.shelf == ()
            assert [p.place.size for p in view.pieces] == ["medium"] * 3

    run(scenario())


def test_refusals_are_tool_errors_naming_the_reason_and_are_logged_refused(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            for name, pid in (("bench_archive", 99), ("bench_restore", ids[0]), ("bench_restore", 99)):
                result = await t.call(call(name, piece_id=pid))
                assert result.is_error and "no_such_piece" in result.content, (name, result.content)
            await t.call(call("bench_archive", piece_id=ids[0]))
            again = await t.call(call("bench_archive", piece_id=ids[0]))
            assert again.is_error and "no_such_piece" in again.content
            rows = await e.workshop.log(e.world.alana, bench)
            assert [r.outcome for r in rows[3:]] == ["no_such_piece"] * 3 + ["accepted", "no_such_piece"]
            assert all(r.by == HER for r in rows[3:])

    run(scenario())


def test_restore_onto_a_full_bench_is_a_full_tool_error(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            first = await put(e, e.world.alana, bench, person_add(e.world.alana, "a"))
            for _ in range(LIMIT - 1):
                await put(e, e.world.alana, bench, person_add(e.world.alana, "x"))
            t = tools(e, bench)
            assert not (await t.call(call("bench_archive", piece_id=first))).is_error
            assert (await put(e, e.world.alana, bench, person_add(e.world.alana, "y"))) is not None
            result = await t.call(call("bench_restore", piece_id=first))
            assert result.is_error and "full" in result.content
            assert [p.id for p in (await e.workshop.read(e.world.alana, bench)).shelf] == [first]

    run(scenario())


def test_bench_shelf_lists_the_shelf_most_recently_archived_first_with_ids_kinds_titles_and_versions(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            assert pieces_with_title(await t.call(call("bench_shelf"))) == []
            for pid in (ids[0], ids[2], ids[1]):
                await t.call(call("bench_archive", piece_id=pid))
            result = await t.call(call("bench_shelf"))
            assert not result.is_error
            listed = pieces_with_title(result)
            assert [(d["id"], d["kind"], d["title"], d["version"]) for d in listed] == [
                (ids[1], "note", "two", 1), (ids[2], "note", "thr", 1), (ids[0], "note", "one", 1)]

    run(scenario())


def test_bench_shelf_shows_a_pieces_current_version(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            from ashley.workshop.commands import Edit
            from ashley.workshop.model import By, Text

            await e.workshop.apply(e.world.alana, bench, Edit(By(e.world.alana.person_id), ids[0], 1, Text("new", "N")))
            await t.call(call("bench_archive", piece_id=ids[0]))
            [only] = pieces_with_title(await t.call(call("bench_shelf")))
            assert (only["id"], only["title"], only["version"]) == (ids[0], "new", 2)

    run(scenario())


def test_bench_read_counts_the_shelved_pieces_and_lists_only_the_layout(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            before = await t.call(call("bench_read"))
            assert values_of(before, "shelved") == [0]
            await t.call(call("bench_archive", piece_id=ids[0]))
            await t.call(call("bench_archive", piece_id=ids[2]))
            after = await t.call(call("bench_read"))
            assert values_of(after, "shelved") == [2]
            assert [d["id"] for d in pieces_with_title(after)] == [ids[1]]
            await t.call(call("bench_restore", piece_id=ids[2]))
            assert values_of(await t.call(call("bench_read")), "shelved") == [1]

    run(scenario())


def test_bench_read_names_the_archive_among_the_latest_changes(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            await t.call(call("bench_archive", piece_id=ids[0]))
            read = await t.call(call("bench_read"))
            assert "archive" in read.content and js(read) is not None

    run(scenario())


def test_a_shelved_piece_takes_no_remove_move_or_read_of_it_as_a_layout_piece(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            await t.call(call("bench_archive", piece_id=ids[1]))
            removed = await t.call(call("bench_remove", piece_id=ids[1]))
            assert removed.is_error and "no_such_piece" in removed.content
            moved = await t.call(call("bench_move", piece_id=ids[1], order=0, size="small"))
            assert moved.is_error and "no_such_piece" in moved.content
            assert [p.id for p in (await e.workshop.read(e.world.alana, bench)).shelf] == [ids[1]]

    run(scenario())


def test_her_undo_takes_back_an_archive_and_a_restore(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            await t.call(call("bench_archive", piece_id=ids[1]))
            assert not (await t.call(call("bench_undo", seq=4))).is_error
            view = await e.workshop.read(e.world.alana, bench)
            assert [p.id for p in view.pieces] == ids and view.shelf == ()
            await t.call(call("bench_archive", piece_id=ids[0]))
            await t.call(call("bench_restore", piece_id=ids[0]))
            assert not (await t.call(call("bench_undo", seq=7))).is_error
            view = await e.workshop.read(e.world.alana, bench)
            assert [p.id for p in view.shelf] == [ids[0]]

    run(scenario())


def test_a_person_can_undo_her_archive(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            await tools(e, bench).call(call("bench_archive", piece_id=ids[1]))
            from ashley.workshop.commands import Undo
            from ashley.workshop.model import By

            got = await e.workshop.apply(e.world.alana, bench, Undo(By(e.world.alana.person_id), 4))
            assert got.outcome == "accepted"
            assert [p.id for p in (await e.workshop.read(e.world.alana, bench)).pieces] == ids

    run(scenario())


def test_missing_or_unknown_arguments_apply_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            t = tools(e, bench)
            for name, args in (("bench_archive", {}), ("bench_restore", {}), ("bench_archive", {"piece_id": "x"}),
                               ("bench_archive", {"piece_id": ids[0], "extra": 1}),
                               ("bench_shelf", {"piece_id": 1})):
                assert (await t.call(call(name, **args))).is_error, (name, args)
            assert len(await e.workshop.log(e.world.alana, bench)) == 3

    run(scenario())


def test_the_tools_act_only_on_their_own_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench, ids = await three(e)
            other = await opened(e, e.world.alana, "other")
            await put(e, e.world.alana, other, person_add(e.world.alana, "o"))
            await tools(e, other).call(call("bench_archive", piece_id=ids[0]))
            assert (await e.workshop.read(e.world.alana, bench)).shelf == ()
            # a person who does not own the bench gets nothing from its shelf
            result = await tools(e, bench, "zed").call(call("bench_shelf"))
            assert result.is_error or pieces_with_title(result) == []

    run(scenario())
