"""Her bench tools build the Command a person's route would, by her, and go through `Workshop.apply`: accepted changes
are logged as hers and announced to the owner, refusals come back as tool errors naming the reason and are logged
refused, and an undo of a person's change works as theirs does."""

from dataclasses import replace

from ashley.live.events import BenchChanged, Shown
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Add, Edit, Move, Remove, Undo
from ashley.workshop.model import HER, By, Place, Text
from bb_support import Env, call, env, js, log, opened, person_add, pieces, put
from contract.conversations_support import run

TOOLS = "bench_add"


def tools(e: Env, bench_id: int, who: str = "alana") -> BenchTools:
    owner = getattr(e.world, who)
    return BenchTools(owner.household_id, owner.person_id, bench_id)


def test_add_builds_her_add_applies_it_logs_it_as_hers_and_announces_it_to_the_owner(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            result = await tools(e, bench).call(call("bench_add", kind="document", title="Plan", body="Dig.",
                                                     size="large"))
            assert not result.is_error
            rows = await log(e, e.world.alana, bench)
            assert [r.command for r in rows] == [Add(HER, "document", Text("Plan", "Dig."), "large")]
            assert (rows[0].outcome, rows[0].by.author) == ("accepted", "ashley")
            view = await e.workshop.read(e.world.alana, bench)
            assert [(p.kind, p.text, p.place) for p in view.pieces] == [("document", Text("Plan", "Dig."),
                                                                         Place(0, "large"))]
            changed = [x for x in e.live.published if isinstance(x, BenchChanged)]
            assert [(x.bench_id, x.seq, x.shown) for x in changed] == [
                (bench, 1, Shown(e.world.alana.household_id, e.world.alana.person_id))]
            assert str(view.pieces[0].id) in result.content

    run(scenario())


def test_a_refused_add_is_a_tool_error_naming_the_reason_logged_refused_and_announced_to_no_one(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t = tools(e, bench)
            cases = {"unknown_kind": dict(kind="hologram", title="t", body="b"),
                     "too_long": dict(kind="note", title="t", body="x" * 4001),
                     "bad_title": dict(kind="note", title=" \t ", body="b")}
            for reason, args in cases.items():
                result = await t.call(call("bench_add", size="small", **args))
                assert result.is_error and reason in result.content, (reason, result.content)
            rows = await log(e, e.world.alana, bench)
            assert [r.outcome for r in rows] == list(cases)
            assert all(r.by == HER and r.piece_id is None for r in rows)
            assert await pieces(e, e.world.alana, bench) == []
            assert not [x for x in e.live.published if isinstance(x, BenchChanged)]

    run(scenario())


def test_a_nul_in_her_title_or_body_is_a_bad_text_tool_error_and_applies_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            t = tools(e, bench)
            for args in (dict(title="a\x00b", body="b"), dict(title="t", body="a\x00b")):
                result = await t.call(call("bench_add", kind="note", size="small", **args))
                assert result.is_error and "bad_text" in result.content, result.content
            assert await log(e, e.world.alana, bench) == []
            assert await pieces(e, e.world.alana, bench) == []
            assert not [x for x in e.live.published if isinstance(x, BenchChanged)]

    run(scenario())


def test_a_full_bench_refuses_her_add_as_full(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            for _ in range(50):
                await put(e, e.world.alana, bench, person_add(e.world.alana))
            result = await tools(e, bench).call(call("bench_add", kind="note", title="t", body="b", size="small"))
            assert result.is_error and "full" in result.content
            assert len(await pieces(e, e.world.alana, bench)) == 50

    run(scenario())


def test_a_huge_body_is_refused_not_stored_and_does_not_raise(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            result = await tools(e, bench).call(call("bench_add", kind="document", title="t", body="x" * 3_000_000,
                                                     size="full"))
            assert result.is_error and "too_long" in result.content
            assert "xxxxxxxxxxxxxxxxxxxx" not in result.content

    run(scenario())


def test_move_and_remove_build_her_commands_and_a_bad_place_or_missing_piece_is_named(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            for title in ("a", "b", "c"):
                await put(e, e.world.alana, bench, person_add(e.world.alana, title))
            t = tools(e, bench)
            assert not (await t.call(call("bench_move", piece_id=3, order=0, size="full"))).is_error
            assert [(p[1], p[4]) for p in await pieces(e, e.world.alana, bench)] == [("c", 0), ("a", 1), ("b", 2)]
            bad = await t.call(call("bench_move", piece_id=1, order=9, size="small"))
            assert bad.is_error and "bad_place" in bad.content
            gone = await t.call(call("bench_remove", piece_id=77))
            assert gone.is_error and "no_such_piece" in gone.content
            assert not (await t.call(call("bench_remove", piece_id=2))).is_error
            rows = await log(e, e.world.alana, bench)
            assert [(type(r.command), r.outcome) for r in rows[3:]] == [
                (Move, "accepted"), (Move, "bad_place"), (Remove, "no_such_piece"), (Remove, "accepted")]
            assert [r.command for r in rows[3:]][0] == Move(HER, 3, Place(0, "full"))
            assert all(r.by == HER for r in rows[3:])

    run(scenario())


def test_her_undo_of_a_persons_change_does_what_theirs_does(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            a, b = await opened(e, e.world.alana, "her"), await opened(e, e.world.alana, "his")
            for bench in (a, b):
                await put(e, e.world.alana, bench, person_add(e.world.alana, "one"))
                await put(e, e.world.alana, bench, person_add(e.world.alana, "two"))
            result = await tools(e, a).call(call("bench_undo", seq=2))
            assert not result.is_error
            await e.workshop.apply(e.world.alana, b, Undo(By(e.world.alana.person_id), 2))
            assert [p[1:4] for p in await pieces(e, e.world.alana, a)] == [p[1:4] for p in await pieces(
                e, e.world.alana, b)] == [("one", "b", 1)]
            ra, rb = await log(e, e.world.alana, a), await log(e, e.world.alana, b)
            assert ra[-1].command == Undo(HER, 2) and (ra[-1].outcome, ra[-1].piece_id) == (rb[-1].outcome,
                                                                                            rb[-1].piece_id)
            redo = await tools(e, a).call(call("bench_undo", seq=3))
            assert redo.is_error and len(await pieces(e, e.world.alana, a)) == 1

    run(scenario())


def test_an_undo_that_cannot_be_applied_is_named_and_the_bench_stays(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana, "one", "b"))
            await put(e, e.world.alana, bench, Edit(By(e.world.alana.person_id), 1, 1, Text("two", "b")))
            t = tools(e, bench)
            stale = await t.call(call("bench_undo", seq=1))
            assert stale.is_error and "changed_since" in stale.content
            nothing = await t.call(call("bench_undo", seq=40))
            assert nothing.is_error and "nothing_to_undo" in nothing.content
            assert [p[1] for p in await pieces(e, e.world.alana, bench)] == ["two"]

    run(scenario())


def test_the_tools_and_a_person_leave_the_same_log_apart_from_who(db_url: str) -> None:
    """The same script, once through her tools and once as a person's Commands: the logs match but for `by`."""

    async def scenario() -> None:
        async with env(db_url) as e:
            a, b = await opened(e, e.world.alana, "tools"), await opened(e, e.world.alana, "person")
            me = By(e.world.alana.person_id)
            t = tools(e, a)
            script = [(call("bench_add", kind="note", title="x", body="1", size="medium"), Add(me, "note",
                                                                                              Text("x", "1"), "medium")),
                      (call("bench_add", kind="document", title="y", body="2", size="full"),
                       Add(me, "document", Text("y", "2"), "full")),
                      (call("bench_move", piece_id=1, order=1, size="small"), Move(me, 1, Place(1, "small"))),
                      (call("bench_move", piece_id=1, order=5, size="small"), Move(me, 1, Place(5, "small"))),
                      (call("bench_edit", piece_id=2, base_version=1, title="Y", body="22"),
                       Edit(me, 2, 1, Text("Y", "22"))),
                      (call("bench_edit", piece_id=2, base_version=1, title="Z", body="3"),
                       Edit(me, 2, 1, Text("Z", "3"))),
                      (call("bench_remove", piece_id=1), Remove(me, 1)),
                      (call("bench_remove", piece_id=1), Remove(me, 1)),
                      (call("bench_undo", seq=7), Undo(me, 7)),
                      (call("bench_undo", seq=7), Undo(me, 7))]
            for tool_call, command in script:
                await t.call(tool_call)
                await e.workshop.apply(e.world.alana, b, command)
            mine = [(replace(r.command, by=me), r.outcome, r.piece_id) for r in await log(e, e.world.alana, a)]
            theirs = [(r.command, r.outcome, r.piece_id) for r in await log(e, e.world.alana, b)]
            assert mine == theirs
            assert len(mine) == len(script) and {r.by for r in await log(e, e.world.alana, a)} == {HER}
            assert await pieces(e, e.world.alana, a) == await pieces(e, e.world.alana, b)

    run(scenario())


def test_a_closed_bench_takes_no_change_from_her_and_the_error_is_a_result(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            await put(e, e.world.alana, bench, person_add(e.world.alana))
            await e.workshop.close(e.world.alana, bench)
            t = tools(e, bench)
            result = await t.call(call("bench_add", kind="note", title="t", body="b", size="small"))
            assert result.is_error
            assert (await t.call(call("bench_remove", piece_id=1))).is_error
            assert len(await log(e, e.world.alana, bench)) == 1

    run(scenario())


def test_the_response_to_a_result_js_is_json_for_a_success(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana)
            result = await tools(e, bench).call(call("bench_read"))
            assert not result.is_error and isinstance(js(result), dict | list)

    run(scenario())
