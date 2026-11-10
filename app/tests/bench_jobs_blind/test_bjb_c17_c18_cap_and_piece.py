"""Contract 17 (a bench turn's runs are capped, counted from the Runs recorded against the turn, so a resume on another pod
counts the same) and contract 18 (the `job` piece is written by code alone)."""

import json
from importlib import resources

from bjb_support import World, call, cfg, job_body, job_pieces, limit, payload, reason, scenario, spec
from ashley import services
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_run import BenchRunTools
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.commands import Add, Edit
from ashley.workshop.model import HER, By, Text
from ashley.workshop.workshop import Workshop
from bench_run_support import code as run_code

RUN = {"base_version": 1, "language": "python"}


async def code_piece(w: World) -> int:
    got = await services.get(Workshop).apply(w.owner, w.bench, run_code(w.owner))
    assert got.piece_id is not None
    return got.piece_id


def runs(w: World, turn: int | None = None) -> BenchRunTools:
    return BenchRunTools(w.owner.household_id, w.owner.person_id, w.bench, w.conversation, turn or w.turn)


async def run_once(tools: BenchRunTools, piece: int, tag: str) -> ToolResult:
    return await tools.call(ToolCall(tag, "bench_run", {"piece_id": piece, **RUN}))


def test_c17_the_run_past_max_runs_per_turn_is_refused_hand_off_and_does_not_run(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await code_piece(w)
        tools = runs(w)
        for i in range(limit("max_runs_per_turn")):
            assert not (await run_once(tools, piece, f"r{i}")).is_error
        refused = await run_once(tools, piece, "over")
        assert reason(refused) == "hand_off"
        assert len(w.box.jobs) == limit("max_runs_per_turn")

    scenario(db_url, body)


def test_c17_a_fresh_tools_object_for_the_same_turn_counts_the_runs_already_made(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await code_piece(w)
        for i in range(limit("max_runs_per_turn")):
            await run_once(runs(w), piece, f"r{i}")
        assert reason(await run_once(runs(w), piece, "after-resume")) == "hand_off"
        assert len(w.box.jobs) == limit("max_runs_per_turn")

    scenario(db_url, body)


def test_c17_the_cap_is_per_turn_not_per_bench(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await code_piece(w)
        for i in range(limit("max_runs_per_turn")):
            await run_once(runs(w), piece, f"r{i}")
        other_turn = w.new_turn()
        assert not (await run_once(runs(w, other_turn), piece, "next-turn")).is_error

    scenario(db_url, body)


def test_c17_a_refused_run_leaves_the_piece_and_the_runs_as_they_were(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await code_piece(w)
        for i in range(limit("max_runs_per_turn")):
            await run_once(runs(w), piece, f"r{i}")
        await run_once(runs(w), piece, "over")
        await run_once(runs(w), piece, "over-again")
        assert (await w.pieces())[piece].version == 1 and len(w.box.jobs) == cfg().max_runs_per_turn

    scenario(db_url, body)


def test_c17_a_hand_off_is_still_possible_after_the_cap(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await code_piece(w)
        for i in range(limit("max_runs_per_turn") + 1):
            await run_once(runs(w), piece, f"r{i}")
        assert not (await w.hand_off(spec(pieces=[piece]))).is_error

    scenario(db_url, body)


def test_c17_reading_the_last_run_is_not_a_run(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await code_piece(w)
        for i in range(limit("max_runs_per_turn")):
            await run_once(runs(w), piece, f"r{i}")
        assert not (await runs(w).call(call("bench_last_run", piece_id=piece))).is_error

    scenario(db_url, body)


# --- 18 ---------------------------------------------------------------------------------------------------------------------


async def job_piece(w: World) -> int:
    return int(payload(await w.hand_off(spec(title="Gate")))["jobs"][0]["piece"])


def test_i10_the_job_kind_is_stored_and_by_code() -> None:
    kind = json.loads(resources.files("ashley.workshop").joinpath("kinds.json").read_text())["job"]
    assert kind["by_code"] is True and kind["family"] == "stored" and kind["format"] == "job"


def test_c18_an_edit_of_a_job_piece_by_the_person_is_refused_bad_body(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await job_piece(w)
        version = (await w.pieces())[piece].version
        got = await services.get(Workshop).apply(w.owner, w.bench, Edit(By(w.owner.person_id), piece, version, Text("Gate", "{}")))
        assert got.outcome == "bad_body"
        assert (await w.pieces())[piece].version == version

    scenario(db_url, body)


def test_c18_an_edit_of_a_job_piece_by_her_is_refused_bad_body(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await job_piece(w)
        version = (await w.pieces())[piece].version
        got = await services.get(Workshop).apply(w.owner, w.bench, Edit(HER, piece, version, Text("Gate", "{}")))
        assert got.outcome == "bad_body"

    scenario(db_url, body)


def test_c18_her_bench_edit_tool_reports_bad_body(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await job_piece(w)
        tools = BenchTools(w.owner.household_id, w.owner.person_id, w.bench)
        await tools.call(call("bench_read_piece", piece_id=piece))
        version = (await w.pieces())[piece].version
        got = await tools.call(call("bench_edit", piece_id=piece, base_version=version, title="Gate", body="{}"))
        assert reason(got) == "bad_body"

    scenario(db_url, body)


def test_c18_a_job_piece_cannot_be_added_by_the_person_or_by_her(db_url: str) -> None:
    async def body(w: World) -> None:
        shop = services.get(Workshop)
        for by in (By(w.owner.person_id), HER):
            got = await shop.apply(w.owner, w.bench, Add(by, "job", Text("fake", "{}"), "medium"))
            assert got.outcome != "accepted"
        assert job_pieces(await w.pieces()) == []

    scenario(db_url, body)


def test_c18_her_bench_add_tool_cannot_make_one(db_url: str) -> None:
    async def body(w: World) -> None:
        got = await BenchTools(w.owner.household_id, w.owner.person_id, w.bench).call(
            call("bench_add", kind="job", title="fake", body="{}"))
        assert got.is_error and job_pieces(await w.pieces()) == []

    scenario(db_url, body)


def test_c18_removing_a_job_piece_is_allowed(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await job_piece(w)
        await w.remove(piece)
        assert piece not in await w.pieces()

    scenario(db_url, body)


def test_c18_the_refusal_leaves_the_pieces_body_as_code_wrote_it(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await job_piece(w)
        before = job_body((await w.pieces())[piece])
        await services.get(Workshop).apply(w.owner, w.bench, Edit(By(w.owner.person_id), piece, 1, Text("Gate", "{}")))
        assert job_body((await w.pieces())[piece]) == before

    scenario(db_url, body)


def test_c18_an_ordinary_piece_is_still_editable_by_the_person(db_url: str) -> None:
    async def body(w: World) -> None:
        note = await w.piece("note", "n", "one")
        got = await services.get(Workshop).apply(w.owner, w.bench, Edit(By(w.owner.person_id), note, 1, Text("n", "two")))
        assert got.outcome == "accepted"

    scenario(db_url, body)
