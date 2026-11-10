"""Contracts 7 and 8 at the proxy: `JobScope` over an inner that offers every bench tool. The agent reads only the pieces
named to it and the ones it made, changes and runs only the ones it made, and has no remove, move, whole-bench read,
propose, house, mail or claude tool."""

import json
from typing import Any

from bjb_support import World, call, reason, row, scenario, scope
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.tools import Catalogue, Tools

ALLOWED = {"bench_read_piece", "bench_add", "bench_add_file", "bench_edit", "bench_run"}
FORBIDDEN = ["bench_read", "bench_remove", "bench_move", "bench_propose", "bench_archive", "bench_undo", "claude_start",
             "claude_prompt", "house_state", "mail_send", "look_up", "bench_tidy_point"]
MADE = 777


class Inner(Tools):
    """Offers every tool by name and records what reaches it; `bench_add` and `bench_add_file` give piece `MADE`."""

    def __init__(self) -> None:
        self.reached: list[ToolCall] = []

    async def catalogue(self) -> Catalogue:
        names = sorted(ALLOWED | set(FORBIDDEN))
        return Catalogue(tuple(ToolSpec(n, f"{n} tool", {"type": "object"}) for n in names), "inner guidance")

    async def call(self, call: ToolCall) -> ToolResult:
        self.reached.append(call)
        if call.name in ("bench_add", "bench_add_file"):
            return ToolResult(call.id, json.dumps({"seq": 9, "piece_id": MADE, "version": 1}))
        return ToolResult(call.id, json.dumps({"ok": True, "tool": call.name}))


async def scoped(w: World, named_ids: tuple[int, ...] = (), made: tuple[int, ...] = ()) -> tuple[Tools, Inner, Any]:
    from bjb_support import named
    await w.started(pieces=[named(i) for i in named_ids])
    job = await w.claimed()
    for piece in made:
        await w.jobs.made(job.id, job.attempts, piece)
    job = await w.jobs.get(w.owner.household_id, w.owner.person_id, job.id)
    inner = Inner()
    return scope(inner, job), inner, job


def test_c08_the_agent_is_offered_exactly_the_five_tools(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, _, _ = await scoped(w)
        assert {s.name for s in (await tools.catalogue()).specs} == ALLOWED

    scenario(db_url, body)


def test_c08_a_tool_that_is_not_offered_is_refused_and_never_reaches_the_inner(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w, (5,))
        for name in FORBIDDEN:
            got = await tools.call(call(name, piece_id=5))
            assert got.is_error, name
        assert inner.reached == []

    scenario(db_url, body)


def test_c07_a_named_piece_reads(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w, (5, 6))
        got = await tools.call(call("bench_read_piece", piece_id=6))
        assert not got.is_error and [c.arguments["piece_id"] for c in inner.reached] == [6]

    scenario(db_url, body)


def test_c07_a_piece_not_named_and_not_made_is_no_such_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w, (5,))
        got = await tools.call(call("bench_read_piece", piece_id=8))
        assert reason(got) == "no_such_piece" and inner.reached == []

    scenario(db_url, body)


def test_c07_a_piece_the_agent_added_reads_afterwards(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, _, job = await scoped(w, (5,))
        assert not (await tools.call(call("bench_add", kind="note", title="t", body="b"))).is_error
        assert not (await tools.call(call("bench_read_piece", piece_id=MADE))).is_error
        assert MADE in row(w.url, job.id)["made"], "a piece it made is recorded on the job"

    scenario(db_url, body)


def test_c07_a_file_the_agent_added_is_recorded_as_made_too(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, _, job = await scoped(w)
        await tools.call(call("bench_add_file", name="a.txt", text="x"))
        assert row(w.url, job.id)["made"] == [MADE]

    scenario(db_url, body)


def test_c07_a_piece_made_by_an_earlier_attempt_reads(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, _, _ = await scoped(w, made=(31,))
        assert not (await tools.call(call("bench_read_piece", piece_id=31))).is_error

    scenario(db_url, body)


def test_c08_edit_of_a_named_piece_it_did_not_make_is_not_yours(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w, (5,))
        got = await tools.call(call("bench_edit", piece_id=5, base_version=1, title="t", body="b"))
        assert reason(got) == "not_yours" and inner.reached == []

    scenario(db_url, body)


def test_c08_edit_of_a_piece_nobody_named_is_not_yours(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w, (5,))
        got = await tools.call(call("bench_edit", piece_id=99, base_version=1, title="t", body="b"))
        assert reason(got) == "not_yours" and inner.reached == []

    scenario(db_url, body)


def test_c08_run_of_a_named_piece_it_did_not_make_is_not_yours(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w, (5,))
        got = await tools.call(call("bench_run", piece_id=5, base_version=1, language="python"))
        assert reason(got) == "not_yours" and inner.reached == []

    scenario(db_url, body)


def test_c08_edit_and_run_of_a_piece_it_made_reach_the_inner(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w)
        await tools.call(call("bench_add", kind="code", title="t", body="print(1)"))
        edited = await tools.call(call("bench_edit", piece_id=MADE, base_version=1, title="t", body="print(2)"))
        ran = await tools.call(call("bench_run", piece_id=MADE, base_version=2, language="python"))
        assert not edited.is_error and not ran.is_error
        assert [c.name for c in inner.reached] == ["bench_add", "bench_edit", "bench_run"]

    scenario(db_url, body)


def test_c08_a_piece_made_by_an_earlier_attempt_is_still_its_to_edit(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, _, _ = await scoped(w, made=(31,))
        assert not (await tools.call(call("bench_edit", piece_id=31, base_version=1, title="t", body="b"))).is_error

    scenario(db_url, body)


def test_c08_an_edit_with_no_piece_id_is_refused_without_reaching_the_inner(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, inner, _ = await scoped(w)
        got = await tools.call(call("bench_edit", base_version=1, title="t", body="b"))
        assert got.is_error and inner.reached == []

    scenario(db_url, body)


def test_c08_the_proxy_keeps_the_inners_guidance_and_adds_none_of_its_own_tools(db_url: str) -> None:
    async def body(w: World) -> None:
        tools, _, _ = await scoped(w)
        got = await tools.catalogue()
        assert len(got.specs) == len({s.name for s in got.specs}) == len(ALLOWED)

    scenario(db_url, body)


