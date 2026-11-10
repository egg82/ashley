"""Malformed arguments, benches that are not hers to touch, `open_bench`, and the logs: tool errors, never exceptions out
of the loop; nothing applied that should be refused; ids and outcomes in the logs, never a title or a body."""

import pytest
from ashley import logs, services
from ashley.tools.bench_tools import BenchTools
from ashley.tools.open_bench import OpenBenchTools, path_of
from ashley.workshop.model import Owner
from ashley.workshop.workshop import NullWorkshop, Workshop
from ashley.inference.model import ToolResult
from bb_support import BENCH_TOOLS, Env, call, dicts, env, js, log, opened, person_add, pieces, put
from contract.conversations_support import run

GOOD: dict[str, dict[str, object]] = {
    "bench_read": {},
    "bench_read_piece": {"piece_id": 1},
    "bench_add": {"kind": "note", "title": "t", "body": "b", "size": "small"},
    "bench_edit": {"piece_id": 1, "base_version": 1, "title": "t", "body": "b"},
    "bench_replace": {"piece_id": 1, "base_version": 1, "old": "b", "new": "c"},
    "bench_move": {"piece_id": 1, "order": 0, "size": "small"},
    "bench_remove": {"piece_id": 1},
    "bench_archive": {"piece_id": 1},
    "bench_shelf": {},
    "bench_restore": {"piece_id": 1},
    "bench_undo": {"seq": 1},
    "bench_rename": {"title": "t"},
    "bench_cue": {"piece_id": 1, "action": "play"},
    "bench_point": {"piece_id": 1, "quote": "q"},
}
MUTATING = tuple(n for n in BENCH_TOOLS if n not in ("bench_read", "bench_read_piece", "bench_shelf"))
WRONG: tuple[object, ...] = (None, "x", "1", [], {}, 1.5, True, [1])


def tools(e: Env, bench_id: int, owner: Owner | None = None) -> BenchTools:
    o = owner or e.world.alana
    return BenchTools(o.household_id, o.person_id, bench_id)


def fields(result: ToolResult) -> dict[str, object]:
    return next(iter(dicts(js(result))))


async def seeded(e: Env) -> int:
    bench = await opened(e, e.world.alana)
    await put(e, e.world.alana, bench, person_add(e.world.alana, "keep", "keep-body"))
    return bench


def test_a_missing_argument_is_a_tool_error_and_applies_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            t = tools(e, bench)
            before = await log(e, e.world.alana, bench)
            for name, good in GOOD.items():
                for key in good:
                    if name == "bench_add" and key == "size":
                        continue  # size is optional
                    args = {k: v for k, v in good.items() if k != key}
                    c = call(name, **args)
                    result = await t.call(c)
                    assert result.is_error and result.call_id == c.id, (name, key)
            assert await log(e, e.world.alana, bench) == before

    run(scenario())


def test_a_wrong_typed_argument_is_a_tool_error_naming_no_value_and_applies_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            t = tools(e, bench)
            before = await log(e, e.world.alana, bench)
            for name, good in GOOD.items():
                for key in good:
                    for wrong in WRONG:
                        if isinstance(wrong, str) and key in ("title", "body", "kind", "size", "quote"):
                            continue  # a string where a string belongs: `decide`'s to judge
                        if name != "bench_add" or key != "size" or wrong is not None:
                            result = await t.call(call(name, **{**good, key: wrong}))
                            assert result.is_error, (name, key, wrong, result.content)
            assert await log(e, e.world.alana, bench) == before

    run(scenario())


def test_an_argument_the_tool_does_not_have_is_an_error_for_a_change(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            t = tools(e, bench)
            before = await log(e, e.world.alana, bench)
            for name in MUTATING:
                result = await t.call(call(name, **GOOD[name], by=99, person_id=99))
                assert result.is_error, name
            assert await log(e, e.world.alana, bench) == before

    run(scenario())


def test_an_unknown_tool_and_an_empty_name_are_errors(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            for name in ("bench_nuke", "", "BENCH_READ", "bench_read ", "bench_read\x00"):
                c = call(name)
                result = await tools(e, bench).call(c)
                assert result.is_error and result.call_id == c.id, name

    run(scenario())


def test_nul_and_huge_strings_never_raise_and_are_never_stored(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            t = tools(e, bench)
            await t.call(call("bench_read_piece", piece_id=1))
            for text in ("a\x00b", "\x00", "y" * 2_000_000):
                for c in (call("bench_add", kind="note", title=text, body="b", size="small"),
                          call("bench_add", kind="note", title="t", body=text, size="small"),
                          call("bench_edit", piece_id=1, base_version=1, title=text, body="b"),
                          call("bench_edit", piece_id=1, base_version=1, title="t", body=text)):
                    result = await t.call(c)
                    assert result.is_error and len(result.content) < 2000
            assert await pieces(e, e.world.alana, bench) == [(1, "keep", "keep-body", 1, 0)]

    run(scenario())


def test_a_huge_or_negative_integer_is_a_tool_error(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            t = tools(e, bench)
            for n in (-1, 0, 2**63, 2**200, -(2**200)):
                for c in (call("bench_read_piece", piece_id=n), call("bench_remove", piece_id=n),
                          call("bench_undo", seq=n), call("bench_move", piece_id=1, order=n if n else -1,
                                                          size="small")):
                    assert (await t.call(c)).is_error, (c.name, n)
            assert await pieces(e, e.world.alana, bench) == [(1, "keep", "keep-body", 1, 0)]

    run(scenario())


def test_the_workshop_out_of_reach_is_an_error_result_not_an_exception(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            services.register(Workshop, NullWorkshop())
            for name, args in GOOD.items():
                assert (await tools(e, bench).call(call(name, **args))).is_error, name

    run(scenario())


def test_tools_for_a_bench_that_is_not_hers_to_serve_refuse_every_call_and_apply_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            before = await log(e, e.world.alana, bench)
            strangers = (tools(e, bench, e.world.sam), tools(e, bench, e.world.zed), tools(e, 9999),
                         BenchTools(e.world.zed.household_id, e.world.alana.person_id, bench),
                         BenchTools(e.world.alana.household_id, 424242, bench))
            for t in strangers:
                for name, args in GOOD.items():
                    result = await t.call(call(name, **args))
                    assert result.is_error and "keep-body" not in result.content, name
            assert await log(e, e.world.alana, bench) == before
            assert await e.workshop.open_benches(e.world.zed) == []

    run(scenario())


def test_open_bench_opens_for_the_speaker_alone_and_returns_its_id_and_path(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            t = OpenBenchTools(e.world.sam.household_id, e.world.sam.person_id)
            assert [s.name for s in (await t.catalogue()).specs] == ["open_bench"]
            first = await t.call(call("open_bench", title="Trip"))
            second = await t.call(call("open_bench", title="Trip"))
            a, b = fields(first), fields(second)
            ia, ib = int(str(a["bench_id"])), int(str(b["bench_id"]))
            assert ia != ib and a["path"] == path_of(ia) == f"/workshop/{ia}"
            mine = await e.workshop.open_benches(e.world.sam)
            assert sorted(x.id for x in mine) == sorted((ia, ib))
            assert {(x.owner_id, x.household_id, x.title) for x in mine} == {
                (e.world.sam.person_id, e.world.sam.household_id, "Trip")}
            assert await e.workshop.open_benches(e.world.alana) == [] == await e.workshop.open_benches(e.world.zed)

    run(scenario())


@pytest.mark.parametrize("arguments", [{}, {"title": ""}, {"title": "   "}, {"title": "a\x00b"}, {"title": "t" * 121},
                                        {"title": "t" * 3_000_000}, {"title": 5}, {"title": None},
                                        {"title": ["t"]}])
def test_open_bench_with_a_bad_title_or_extra_field_is_an_error_and_opens_nothing(db_url: str,
                                                                                 arguments: dict[str, object]) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            t = OpenBenchTools(e.world.alana.household_id, e.world.alana.person_id)
            result = await t.call(call("open_bench", **arguments))
            assert result.is_error and len(result.content) < 2000
            assert await e.workshop.open_benches(e.world.alana) == []

    run(scenario())


def test_open_bench_with_an_extra_field_is_an_error_and_opens_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            t = OpenBenchTools(e.world.alana.household_id, e.world.alana.person_id)
            assert (await t.call(call("open_bench", title="ok", person_id=3))).is_error
            assert await e.workshop.open_benches(e.world.alana) == []

    run(scenario())


def test_open_bench_for_nobody_or_with_no_workshop_is_an_error(db_url: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            ghost = OpenBenchTools(e.world.alana.household_id, 987654)
            assert (await ghost.call(call("open_bench", title="x"))).is_error
            wrong_home = OpenBenchTools(e.world.zed.household_id, e.world.alana.person_id)
            assert (await wrong_home.call(call("open_bench", title="x"))).is_error
            assert (await OpenBenchTools(1, 1).call(call("open_bench_x", title="x"))).is_error
            services.register(Workshop, NullWorkshop())
            nowhere = OpenBenchTools(e.world.alana.household_id, e.world.alana.person_id)
            assert (await nowhere.call(call("open_bench", title="x"))).is_error

    run(scenario())


def test_logs_carry_ids_and_outcomes_never_a_title_or_a_body(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    secret_t, secret_b, secret_n = "TITLE-planted-8431", "BODY-planted-8431", "NEWBODY-planted-8431"
    logs.setup({"LOG_LEVEL": "debug"})

    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await opened(e, e.world.alana, "BENCHTITLE-planted-8431")
            await put(e, e.world.alana, bench, person_add(e.world.alana, secret_t, secret_b))
            capsys.readouterr()
            t = tools(e, bench)
            await t.call(call("bench_read"))
            await t.call(call("bench_read_piece", piece_id=1))
            await t.call(call("bench_edit", piece_id=1, base_version=1, title=secret_t, body=secret_n))
            await t.call(call("bench_add", kind="note", title=secret_t, body=secret_b, size="small"))
            await t.call(call("bench_add", kind="hologram", title=secret_t, body=secret_b, size="small"))
            await t.call(call("bench_add", kind="note", title=secret_t, body=secret_b + "\x00", size="small"))
            await t.call(call("bench_add", kind="note", title=secret_t, body=secret_b * 800, size="small"))
            await t.call(call("bench_edit", piece_id=secret_b, base_version=1, title=secret_t, body=secret_n))
            await t.call(call("bench_move", piece_id=secret_b, order=0, size="small"))
            await t.call(call("bench_edit", piece_id=1, base_version=2, title=secret_t, body=secret_n))
            await t.call(call("bench_nuke"))
            await OpenBenchTools(e.world.alana.household_id, e.world.alana.person_id).call(
                call("open_bench", title="OPENTITLE-planted-8431"))
            await OpenBenchTools(e.world.alana.household_id, e.world.alana.person_id).call(
                call("open_bench", title="OPENTITLE-planted-8431\x00"))
            for c in range(3):
                await t.call(call("bench_undo", seq=c + 1))

    run(scenario())
    out = capsys.readouterr()
    text = out.out + out.err
    assert "planted-8431" not in text
    lines = [ln for ln in text.splitlines() if "event=tools.call" in ln]
    assert len(lines) == 16
    assert any("tool=bench_edit" in ln for ln in lines) and any("tool=open_bench" in ln for ln in lines)
    assert all("outcome=" in ln for ln in lines)


@pytest.mark.parametrize("size", ["huge", "", "MEDIUM", "full ", " "])
def test_a_size_that_is_not_one_of_the_four_is_an_error_and_applies_nothing(db_url: str, size: str) -> None:
    async def scenario() -> None:
        async with env(db_url) as e:
            bench = await seeded(e)
            t = tools(e, bench)
            before = await log(e, e.world.alana, bench)
            assert (await t.call(call("bench_add", kind="note", title="t", body="b", size=size))).is_error
            assert (await t.call(call("bench_move", piece_id=1, order=0, size=size))).is_error
            assert [r.outcome for r in await log(e, e.world.alana, bench)][: len(before)] == [r.outcome for r in before]
            assert await pieces(e, e.world.alana, bench) == [(1, "keep", "keep-body", 1, 0)]

    run(scenario())
