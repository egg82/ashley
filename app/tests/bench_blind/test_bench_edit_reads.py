"""An edit replaces the whole body, so she may edit only a version she read whole or wrote whole in the same turn;
anything else is refused `unread` before the Workshop sees it. A body cut on read says so in a field."""

from ashley.inference.model import ToolCall
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Edit, Move
from ashley.workshop.model import HER, By, Place, Text
from bb_support import Env, call, env, log, opened, person_add, pieces, piece_in, put, values_of
from contract.conversations_support import run

CUT = 600       # `read_body_chars`
WHOLE = 12000   # `piece_chars`


def tools(e: Env, bench_id: int) -> BenchTools:
    return BenchTools(e.world.alana.household_id, e.world.alana.person_id, bench_id)


def edit(piece_id: int = 1, version: int = 1, title: str = "new", body: str = "new body") -> ToolCall:
    return call("bench_edit", piece_id=piece_id, base_version=version, title=title, body=body)


async def refused_unread(e: Env, t: BenchTools, bench: int, c: ToolCall) -> None:
    before = await log(e, e.world.alana, bench)
    result = await t.call(c)
    assert result.is_error and "unread" in result.content, result.content
    assert await log(e, e.world.alana, bench) == before


def test_an_edit_of_a_piece_she_has_not_read_is_unread_and_nothing_reaches_the_workshop(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "short"))
            await refused_unread(e, tools(e, bench), bench, edit())
            assert (await pieces(e, e.world.alana, bench))[0][1:4] == (("t", "short", 1))

    run(scenario())


def test_a_piece_read_whole_in_the_bench_read_can_then_be_edited_as_hers(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "short"))
            t = tools(e, bench)
            read = await t.call(call("bench_read"))
            assert piece_in(read, 1)["body_cut"] is False
            done = await t.call(edit())
            assert not done.is_error, done.content
            assert (await log(e, e.world.alana, bench))[-1].command == Edit(HER, 1, 1, Text("new", "new body"))
            assert (await pieces(e, e.world.alana, bench))[0][1:4] == ("new", "new body", 2)

    run(scenario())


def test_a_body_cut_on_read_says_so_and_the_piece_seen_only_cut_cannot_be_edited(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "long", "y" * (CUT + 1)))
            await put(e, e.world.alana, bench, person_add(e.world.alana, "edge", "e" * CUT))
            t = tools(e, bench)
            read = await t.call(call("bench_read"))
            long, edge = piece_in(read, 1), piece_in(read, 2)
            assert long["body_cut"] is True and edge["body_cut"] is False
            assert isinstance(long["body"], str) and len(long["body"]) <= CUT + 20
            assert edge["body"] == "e" * CUT
            await refused_unread(e, t, bench, edit(1, 1))
            assert not (await t.call(edit(2, 1))).is_error

    run(scenario())


def test_reading_the_piece_whole_lifts_the_refusal_and_a_piece_longer_than_the_limit_cannot_be_edited(
        db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "mid", "m" * 5000, "document"))
            await put(e, e.world.alana, bench, person_add(e.world.alana, "huge", "h" * (WHOLE + 1), "document"))
            t = tools(e, bench)
            whole = await t.call(call("bench_read_piece", piece_id=1))
            assert piece_in(whole, 1)["body"] == "m" * 5000 and piece_in(whole, 1)["body_cut"] is False
            assert not (await t.call(edit(1, 1))).is_error
            cut = await t.call(call("bench_read_piece", piece_id=2))
            assert not cut.is_error and True in values_of(cut, "body_cut")
            assert len(str(piece_in(cut, 2)["body"])) <= WHOLE + 20
            await refused_unread(e, t, bench, edit(2, 1))

    run(scenario())


def test_what_she_wrote_whole_she_may_edit_again_even_over_the_read_limit(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t = tools(e, bench)
            await t.call(call("bench_add", kind="document", title="d", body="w" * (WHOLE + 500), size="full"))
            first = await t.call(edit(1, 1, "d2", "v2"))
            assert not first.is_error, first.content
            second = await t.call(edit(1, 2, "d3", "v3"))
            assert not second.is_error, second.content
            assert (await pieces(e, e.world.alana, bench))[0][1:4] == ("d3", "v3", 3)

    run(scenario())


def test_an_edit_on_a_version_she_never_read_is_unread_even_if_she_read_an_older_one(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "v1"))
            t = tools(e, bench)
            await t.call(call("bench_read_piece", piece_id=1))
            await put(e, e.world.alana, bench, Edit(By(e.world.alana.person_id), 1, 1, Text("t", "v2 by person")))
            await refused_unread(e, t, bench, edit(1, 2))
            stale = await t.call(edit(1, 1))
            assert stale.is_error and "stale_base" in stale.content and "unread" not in stale.content
            await t.call(call("bench_read_piece", piece_id=1))
            assert not (await t.call(edit(1, 2))).is_error

    run(scenario())


def test_a_move_by_someone_does_not_make_an_unread_body_read(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "v1"))
            t = tools(e, bench)
            await t.call(call("bench_move", piece_id=1, order=0, size="full"))
            await refused_unread(e, t, bench, edit())
            await put(e, e.world.alana, bench, Move(By(e.world.alana.person_id), 1, Place(0, "small")))
            await refused_unread(e, t, bench, edit())

    run(scenario())


def test_a_new_turns_tools_have_read_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "v1"))
            await tools(e, bench).call(call("bench_read_piece", piece_id=1))
            await refused_unread(e, tools(e, bench), bench, edit())

    run(scenario())


def test_reading_a_piece_that_is_not_there_or_is_another_benchs_reads_nothing_and_leaks_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a, b = await opened(e, e.world.alana, "a"), await opened(e, e.world.alana, "b")
            await put(e, e.world.alana, a, person_add(e.world.alana, "t", "on-a"))
            await put(e, e.world.alana, b, person_add(e.world.alana, "t", "on-b"))
            await put(e, e.world.alana, b, person_add(e.world.alana, "only-b", "SECRET-ONLY-B"))
            t = tools(e, a)
            miss = await t.call(call("bench_read_piece", piece_id=2))
            assert miss.is_error and "SECRET-ONLY-B" not in miss.content
            for c in (edit(2, 1), call("bench_remove", piece_id=2), call("bench_move", piece_id=2, order=0, size="full")):
                result = await t.call(c)
                assert result.is_error
            assert len(await pieces(e, e.world.alana, b)) == 2 and await pieces(e, e.world.alana, b) == [
                (1, "t", "on-b", 1, 0), (2, "only-b", "SECRET-ONLY-B", 1, 1)]
            undo = await t.call(call("bench_undo", seq=2))
            assert undo.is_error and "nothing_to_undo" in undo.content
            assert len(await pieces(e, e.world.alana, b)) == 2

    run(scenario())


def test_the_latest_commands_in_a_read_are_at_most_the_configured_number_and_end_at_the_newest(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            for _ in range(15):
                await put(e, e.world.alana, bench, person_add(e.world.alana))
            read = await tools(e, bench).call(call("bench_read"))
            seqs = [s for s in values_of(read, "seq") if isinstance(s, int)]
            assert 1 <= len(seqs) <= 12 and max(seqs) == 15

    run(scenario())


def test_her_own_move_or_a_refused_edit_does_not_cost_her_what_she_read(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "t", "v1"))
            await put(e, e.world.alana, bench, person_add(e.world.alana, "u", "v1"))
            t = tools(e, bench)
            await t.call(call("bench_read"))
            await t.call(call("bench_move", piece_id=1, order=1, size="full"))
            await t.call(call("bench_remove", piece_id=2))
            assert (await t.call(edit(1, 9))).is_error
            assert not (await t.call(edit(1, 1))).is_error

    run(scenario())


def test_a_body_is_cut_by_characters_and_says_so_whatever_the_alphabet(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "emoji", "\U0001F600" * (CUT + 1)))
            await put(e, e.world.alana, bench, person_add(e.world.alana, "accent", "é" * CUT))
            read = await tools(e, bench).call(call("bench_read"))
            assert piece_in(read, 1)["body_cut"] is True
            assert piece_in(read, 2)["body_cut"] is False and piece_in(read, 2)["body"] == "é" * CUT

    run(scenario())
