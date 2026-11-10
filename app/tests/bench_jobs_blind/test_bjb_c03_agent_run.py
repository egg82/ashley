"""Contracts 3, 7, 8, 9 (the retake's first message) and 10 through `bench_agent.run` over the real Workshop with a scripted
model: what the agent is shown, what it can change, what it hands back."""

import asyncio
from typing import Any

from bjb_support import (MARK_BODY, MARK_BRIEF, MARK_TITLE, World, bench_agent, calls_of, everything_shown, finished,
                         first_user_message, limit, named, new_job, payload, reason, results_seen, row, scenario)
from files_support import PNG
from ashley.inference.model import Prompt, ToolCalls, ToolResults

UNNAMED_T, UNNAMED_B = "UNNAMED-TITLE-aa11", "UNNAMED-BODY-bb22"
SHELVED_T, OTHER_T = "SHELVED-TITLE-cc33", "OTHERBENCH-TITLE-dd44"
ALLOWED = {"bench_read_piece", "bench_add", "bench_add_file", "bench_edit", "bench_run"}


async def with_pieces(w: World) -> dict[str, int]:
    for n in range(9):  # piece ids count per bench: the other bench's piece must not share an id with one on this bench
        await w.piece("note", f"filler{n}", "f", bench=w.other_bench)
    ids = {
        "named": await w.piece("note", MARK_TITLE, MARK_BODY),
        "unnamed": await w.piece("note", UNNAMED_T, UNNAMED_B),
        "shelved": await w.piece("note", SHELVED_T, "shelved body"),
        "other": await w.piece("note", OTHER_T, "other body", bench=w.other_bench),
        "pic": await w.file_piece(PNG, "named-pic.png"),
        "stranger": await w.file_piece(PNG + b"\x01", "UNNAMED-PIC-ee55.png"),
    }
    await w.shelve(ids["shelved"])
    return ids


async def claimed_run(w: World, pieces: list[Any], brief: str = MARK_BRIEF) -> tuple[Any, Any]:
    await w.started(pieces=pieces, brief=brief)
    job = await w.claimed()
    return job, await bench_agent.run(job)


def test_c03_the_first_message_carries_the_brief_and_each_named_pieces_content(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await with_pieces(w)
        w.model.script = [finished()]
        await claimed_run(w, [named(ids["named"])])
        task, prompt = w.model.asked[0]
        assert task == "bench_job"
        first = first_user_message(prompt)
        assert MARK_BRIEF in first and MARK_BODY in first

    scenario(db_url, body)


def test_c03_a_piece_not_named_appears_in_no_prompt_and_no_tool_result_of_the_job(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await with_pieces(w)
        w.model.script = [
            calls_of(("bench_read_piece", {"piece_id": ids["named"]}), ("bench_read_piece", {"piece_id": ids["unnamed"]}),
                     ("bench_read_piece", {"piece_id": ids["other"]}), ("bench_read_piece", {"piece_id": ids["shelved"]})),
            finished()]
        await claimed_run(w, [named(ids["named"])])
        shown = everything_shown(w.model)
        for mark in (UNNAMED_T, UNNAMED_B, SHELVED_T, "shelved body", OTHER_T, "other body", "UNNAMED-PIC-ee55"):
            assert mark not in shown, mark
        errors = [reason(r) for r in results_seen(w.model) if r.is_error]
        assert errors == ["no_such_piece"] * 3
        assert MARK_BODY in shown

    scenario(db_url, body)


def test_c03_the_bytes_title_and_size_of_an_unnamed_file_are_never_shown(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await with_pieces(w)
        w.model.script = [finished()]
        await claimed_run(w, [named(ids["named"])])
        shown = everything_shown(w.model)
        assert "UNNAMED-PIC" not in shown and "named-pic" not in shown

    scenario(db_url, body)


def test_c03_a_named_large_piece_is_shown_by_name_type_and_size_never_its_bytes(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await with_pieces(w)
        w.model.script = [finished()]
        await claimed_run(w, [named(ids["pic"])])
        first = first_user_message(w.model.asked[0][1])
        assert "named-pic.png" in first and "image/png" in first and str(len(PNG)) in first
        assert PNG.decode("latin-1") not in everything_shown(w.model)

    scenario(db_url, body)


def test_c08_the_agents_tools_are_the_five_and_no_whole_bench_read(db_url: str) -> None:
    async def body(w: World) -> None:
        w.model.script = [finished()]
        await claimed_run(w, [])
        assert {t.name for t in w.model.asked[0][1].tools} == ALLOWED

    scenario(db_url, body)


def test_c07_c08_through_the_loop_reads_are_limited_edits_and_runs_are_not_yours_and_its_own_work_goes_through(
        db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await with_pieces(w)
        named_id = ids["named"]

        def edit_mine(p: Prompt) -> ToolCalls:
            return calls_of(("bench_edit", {"piece_id": last_added(p), "base_version": 1, "title": "mine", "body": "print(2)"}))

        w.model.script = [
            calls_of(("bench_edit", {"piece_id": named_id, "base_version": 1, "title": "x", "body": "y"}),
                     ("bench_run", {"piece_id": named_id, "base_version": 1, "language": "python"}),
                     ("bench_add", {"kind": "code", "title": "mine", "body": "print(1)"})),
            edit_mine,
            finished("built it")]
        job, _ = await claimed_run(w, [named(named_id)])
        seen = results_seen(w.model)
        assert [reason(r) for r in seen if r.is_error] == ["not_yours", "not_yours"]
        mine = (await w.pieces())
        assert mine[named_id].version == 1 and mine[named_id].text.body == MARK_BODY
        made = row(w.url, job.id)["made"]
        assert len(made) == 1 and mine[made[0]].text.body == "print(2)" and mine[made[0]].version == 2

    scenario(db_url, body)


def last_added(prompt: Prompt) -> int:
    for entry in reversed(prompt.messages):
        if isinstance(entry, ToolResults):
            for r in entry.results:
                if not r.is_error and "piece_id" in r.content:
                    return int(payload(r)["piece_id"])
    raise AssertionError("nothing was added yet")


def test_c05_the_outcome_names_only_pieces_it_made_whatever_the_model_claims(db_url: str) -> None:
    async def body(w: World) -> None:
        ids = await with_pieces(w)

        def claims(p: Prompt) -> dict[str, Any]:
            return finished("done it", [last_added(p), ids["named"], 99999])

        w.model.script = [
            calls_of(("bench_add", {"kind": "note", "title": "mine", "body": "b"})),
            claims]
        job, out = await claimed_run(w, [named(ids["named"])])
        made = row(w.url, job.id)["made"]
        assert out.state == "done" and list(out.outputs) == made and len(made) == 1
        assert out.summary == "done it"

    scenario(db_url, body)


def test_c13_a_summary_longer_than_result_chars_is_cut(db_url: str) -> None:
    async def body(w: World) -> None:
        w.model.script = [finished("s" * (limit("result_chars") * 4))]
        _, out = await claimed_run(w, [])
        assert out.state == "done" and 0 < len(out.summary) <= limit("result_chars")

    scenario(db_url, body)


def test_c13_a_model_that_says_it_did_not_finish_is_a_failed_job(db_url: str) -> None:
    async def body(w: World) -> None:
        w.model.script = [{"done": False, "summary": "could not", "pieces": []}]
        _, out = await claimed_run(w, [])
        assert out.state == "failed"

    scenario(db_url, body)


def test_c14_a_loop_that_never_answers_stops_within_agent_max_tool_rounds(db_url: str) -> None:
    async def body(w: World) -> None:
        w.model.script = [calls_of(("bench_read_piece", {"piece_id": 1}), prefix=f"r{i}-")
                          for i in range(limit("agent_max_tool_rounds") * 3)] + [finished("late")]
        _, out = await claimed_run(w, [])
        assert len(w.model.asked) <= limit("agent_max_tool_rounds") + 2
        assert out.state in ("done", "failed")

    scenario(db_url, body)


def test_c09_a_retake_is_told_its_earlier_attempts_pieces_are_there_to_continue_from(db_url: str) -> None:
    async def body(w: World) -> None:
        earlier = await w.piece("note", "earlier-attempt", "EARLIER-ATTEMPT-BODY-ff66")
        await w.started(brief=MARK_BRIEF)
        first = await w.claimed()
        await w.jobs.made(first.id, first.attempts, earlier)
        from bjb_support import age, cfg
        age(w.url, first.id, "claimed_at", cfg().claim_s * 10)
        await w.jobs.sweep(cfg().claim_s, None)
        again = await w.claimed()
        assert again.attempts == first.attempts + 1
        w.model.script = [finished()]
        await bench_agent.run(again)
        message = first_user_message(w.model.asked[0][1])
        assert MARK_BRIEF in message and "EARLIER-ATTEMPT-BODY-ff66" in message

    scenario(db_url, body)


def test_c09_a_first_attempt_is_told_of_no_earlier_pieces(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.piece("note", "bystander", "BYSTANDER-BODY-gg77")
        w.model.script = [finished()]
        await claimed_run(w, [])
        assert "BYSTANDER-BODY-gg77" not in everything_shown(w.model)

    scenario(db_url, body)


def test_c10_two_jobs_on_one_bench_never_change_the_same_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        shared = await w.piece("note", "shared", "SHARED-BODY")
        await w.start(new_job(w, title="one", brief="JOB-ONE", pieces=[named(shared)], piece_id=11),
                    new_job(w, title="two", brief="JOB-TWO", pieces=[named(shared)], piece_id=12))

        def steal(p: Prompt) -> ToolCalls:
            return calls_of(("bench_edit", {"piece_id": last_added(p), "base_version": 1, "title": "own", "body": "x"}),
                            ("bench_edit", {"piece_id": shared, "base_version": 1, "title": "t", "body": "THEFT"}))

        def script() -> list[Any]:
            return [calls_of(("bench_add", {"kind": "code", "title": "own", "body": "print(1)"})), steal, finished()]

        w.model.routed = {"JOB-ONE": script(), "JOB-TWO": script()}
        a, b = await w.claimed(), await w.claimed()
        await asyncio.gather(bench_agent.run(a), bench_agent.run(b))
        mine, theirs = row(w.url, a.id)["made"], row(w.url, b.id)["made"]
        assert len(mine) == 1 and len(theirs) == 1 and not set(mine) & set(theirs)
        pieces = await w.pieces()
        assert pieces[shared].version == 1 and pieces[shared].text.body == "SHARED-BODY"
        assert [reason(r) for r in results_seen(w.model) if r.is_error] == ["not_yours", "not_yours"]
        assert pieces[mine[0]].version == 2 and pieces[theirs[0]].version == 2

    scenario(db_url, body)


def test_c10_a_third_job_cannot_touch_what_the_first_two_made(db_url: str) -> None:
    async def body(w: World) -> None:
        await w.started(brief="JOB-ONE")
        first = await w.claimed()
        w.model.script = [calls_of(("bench_add", {"kind": "note", "title": "m", "body": "mine"})), finished()]
        await bench_agent.run(first)
        (made,) = row(w.url, first.id)["made"]
        await w.started(brief="JOB-THREE")
        third = await w.claimed()
        w.model.asked.clear()
        w.model.script = [calls_of(("bench_edit", {"piece_id": made, "base_version": 1, "title": "t", "body": "x"}),
                                   ("bench_read_piece", {"piece_id": made})), finished()]
        await bench_agent.run(third)
        assert [reason(r) for r in results_seen(w.model) if r.is_error] == ["not_yours", "no_such_piece"]
        assert (await w.pieces())[made].text.body == "mine"

    scenario(db_url, body)
