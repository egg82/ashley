"""Contracts 13 (the job piece), 14, 15 and 21 through `BenchJobRunner`: ticks claim and step the jobs, a deadline ends a
job `timed_out` with what it made kept, a cancel stops the worker, and a job finishing first changes only its own piece."""

from typing import Any

from ashley.inference.model import Prompt

from bjb_support import (HANG, MARK_BRIEF, World, age, call, calls_of, cfg, expire, finished, job_body, limit, payload, row,
                         scenario, spec, state_of, wake_count, watch_tick)


async def handed(w: World, *specs: dict[str, Any], can_code: bool = False) -> list[dict[str, Any]]:
    got = payload(await w.hand_off(*specs, can_code=can_code))
    return list(got["jobs"])


async def body_of_piece(w: World, piece: int) -> dict[str, Any]:
    return job_body((await w.pieces())[piece])


def made_of(w: World, job: int) -> list[int]:
    return list(row(w.url, job)["made"] or [])


# --- 13: the job piece shows the finish ---------------------------------------------------------------------------------


def test_c13_a_finished_agent_job_shows_its_state_summary_and_outputs_on_its_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec(brief=MARK_BRIEF))

        def built(_: Prompt) -> dict[str, Any]:
            return finished("it is built", _made(w, job["job"]))

        w.model.script = [calls_of(("bench_add", {"kind": "note", "title": "out", "body": "made"})), built]
        await w.ticks()
        stored = row(w.url, job["job"])
        assert stored["state"] == "done" and stored["summary"] == "it is built" and len(stored["outputs"]) == 1
        shown = await body_of_piece(w, job["piece"])
        assert shown["state"] == "done" and shown["outputs"] == stored["outputs"] and shown["files_refused"] == 0
        assert shown["worker"] == "agent" and shown["finished"] is not None

    scenario(db_url, body)


def _made(w: World, job: int) -> list[int]:
    return made_of(w, job)


def test_c13_a_failed_job_shows_a_reason_code_on_its_piece(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        w.model.script = [{"done": False, "summary": "could not", "pieces": []}]
        await w.ticks()
        shown = await body_of_piece(w, job["piece"])
        assert shown["state"] == "failed" and shown["reason"]

    scenario(db_url, body)


def test_c13_the_job_piece_follows_the_job_through_its_states(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec("claude_code"), can_code=True)
        await w.ticks(3)
        assert (await body_of_piece(w, job["piece"]))["state"] in ("starting", "running")
        sid = next(iter(w.bridge.sessions_))
        w.bridge.settle(sid, "blocked")
        await w.ticks(3)
        assert (await body_of_piece(w, job["piece"]))["state"] == "blocked"
        w.bridge.out[sid] = {"RESULT.md": b"all done"}
        w.bridge.settle(sid, "done")
        await w.ticks(3)
        shown = await body_of_piece(w, job["piece"])
        assert shown["state"] == "done" and row(w.url, job["job"])["summary"] == "all done"

    scenario(db_url, body)


# --- 21 and 20 end to end -----------------------------------------------------------------------------------------------


def test_c21_c20_a_job_finishing_first_changes_only_its_own_piece_and_wakes_nothing_until_the_last_settles(
        db_url: str) -> None:
    async def body(w: World) -> None:
        agent, code = await handed(w, spec("agent", title="agent"), spec("claude_code", title="code"), can_code=True)
        w.model.script = [finished("agent done")]
        await watch_tick(w)
        await w.ticks(4)
        assert state_of(w.url, agent["job"]) == "done"
        code_before = await body_of_piece(w, code["piece"])
        assert code_before["state"] in ("starting", "running") and (await body_of_piece(w, agent["piece"]))["state"] == "done"
        await watch_tick(w)
        assert wake_count(w.url) == 0
        sid = next(iter(w.bridge.sessions_))
        w.bridge.out[sid] = {"RESULT.md": b"code done"}
        w.bridge.settle(sid, "done")
        await w.ticks(4)
        assert state_of(w.url, code["job"]) == "done"
        await watch_tick(w)
        assert wake_count(w.url) == 1

    scenario(db_url, body)


def test_c21_the_other_jobs_piece_is_byte_for_byte_unchanged_by_a_sibling_finishing(db_url: str) -> None:
    async def body(w: World) -> None:
        _, code = await handed(w, spec("agent", title="agent"), spec("claude_code", title="code"), can_code=True)
        await w.ticks(2)
        before = (await w.pieces())[code["piece"]]
        w.model.script = [finished("agent done")]
        await w.ticks(4)
        after = (await w.pieces())[code["piece"]]
        assert (after.text, after.version) == (before.text, before.version)

    scenario(db_url, body)


# --- 14 --------------------------------------------------------------------------------------------------------------------


def test_c14_past_the_deadline_an_agent_job_ends_timed_out_and_the_pieces_it_made_stay(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        w.model.script = [calls_of(("bench_add", {"kind": "note", "title": "kept", "body": "KEPT-BODY"})), HANG]
        await w.ticks(4)
        (kept,) = made_of(w, job["job"])
        assert state_of(w.url, job["job"]) == "running"
        expire(w.url, job["job"])
        await w.ticks(4)
        stored = row(w.url, job["job"])
        assert stored["state"] == "timed_out" and stored["finished_at"] is not None
        assert (await w.pieces())[kept].text.body == "KEPT-BODY"
        assert (await body_of_piece(w, job["piece"]))["state"] == "timed_out"

    scenario(db_url, body)


def test_c14_an_agent_task_past_its_deadline_is_cancelled_and_asks_the_model_nothing_more(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        w.model.script = [HANG]
        await w.ticks(3)
        asked = len(w.model.asked)
        expire(w.url, job["job"])
        w.model.script = [finished("too late")]
        await w.ticks(5)
        assert len(w.model.asked) == asked and state_of(w.url, job["job"]) == "timed_out"

    scenario(db_url, body)


def test_c14_past_the_deadline_a_claude_code_job_collects_out_as_it_stands_and_ends_timed_out(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec("claude_code"), can_code=True)
        await w.ticks(3)
        sid = next(iter(w.bridge.sessions_))
        w.bridge.out[sid] = {"partial.txt": b"so far\n"}
        expire(w.url, job["job"])
        await w.ticks(4)
        stored = row(w.url, job["job"])
        assert stored["state"] == "timed_out" and len(stored["outputs"]) == 1
        assert (await body_of_piece(w, job["piece"]))["outputs"] == stored["outputs"]

    scenario(db_url, body)


def test_c14_a_group_still_unsettled_past_group_timeout_ends_its_unfinished_jobs_and_wakes_once(db_url: str) -> None:
    async def body(w: World) -> None:
        quick, stuck = await handed(w, spec(title="quick"), spec("claude_code", title="stuck"), can_code=True)
        w.model.script = [finished("quick done")]
        await w.ticks(4)
        await watch_tick(w)
        assert wake_count(w.url) == 0
        age(w.url, stuck["job"], "created_at", (limit("group_timeout_min") + 1) * 60)
        age(w.url, quick["job"], "created_at", (limit("group_timeout_min") + 1) * 60)
        await w.ticks(4)
        assert state_of(w.url, quick["job"]) == "done" and state_of(w.url, stuck["job"]) == "timed_out"
        await watch_tick(w)
        assert wake_count(w.url) == 1

    scenario(db_url, body)


# --- 15 --------------------------------------------------------------------------------------------------------------------


def test_c15_the_cancel_tool_ends_the_job_cancelled(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        got = await w.tools().call(call("bench_job_cancel", job=job["job"]))
        assert not got.is_error, got.content
        assert state_of(w.url, job["job"]) == "cancelled"
        again = await w.tools().call(call("bench_job_cancel", job=job["job"]))  # AMBIGUITY: a repeat answers what the job is
        assert not again.is_error and payload(again)["state"] == "cancelled"

    scenario(db_url, body)


def test_c15_the_cancel_tool_refuses_a_job_that_is_not_the_speakers(db_url: str) -> None:
    async def body(w: World) -> None:
        from bjb_support import new_job
        from dataclasses import replace
        _, (theirs,) = await w.start(replace(new_job(w), person=w.mate.person_id, bench=w.foreign_bench))
        got = await w.tools().call(call("bench_job_cancel", job=theirs))
        assert got.is_error and state_of(w.url, theirs) == "due"
        assert (await w.tools().call(call("bench_job_cancel", job=424242))).is_error

    scenario(db_url, body)


def test_c15_a_cancelled_job_that_was_never_started_is_never_run(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        await w.tools().call(call("bench_job_cancel", job=job["job"]))
        await w.ticks(4)
        assert w.model.asked == [] and state_of(w.url, job["job"]) == "cancelled"

    scenario(db_url, body)


def test_c15_an_agent_stops_at_its_next_step_when_cancelled_and_its_cancel_is_not_overwritten(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())

        async def cancelling(prompt: Any) -> Any:
            await w.jobs.cancel(w.owner.household_id, w.owner.person_id, job["job"])
            return calls_of(("bench_add", {"kind": "note", "title": "two", "body": "b"}), prefix="m")

        add = calls_of(("bench_add", {"kind": "note", "title": "one", "body": "b"}))
        w.model.script = [add, cancelling, calls_of(("bench_add", {"kind": "note", "title": "three", "body": "b"}), prefix="z"),
                          calls_of(("bench_add", {"kind": "note", "title": "four", "body": "b"}), prefix="y"),
                          finished("never")]
        await w.ticks(10)
        stored = row(w.url, job["job"])
        assert stored["state"] == "cancelled" and stored["summary"] is None
        assert len(w.model.asked) <= 3 and len(made_of(w, job["job"])) <= 2

    scenario(db_url, body)


def test_c15_cancelling_a_claude_code_job_closes_its_session(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec("claude_code"), can_code=True)
        await w.ticks(3)
        sid = next(iter(w.bridge.sessions_))
        await w.tools(can_code=True).call(call("bench_job_cancel", job=job["job"]))
        await w.ticks(4)
        assert w.bridge.closed == [sid] and state_of(w.url, job["job"]) == "cancelled"

    scenario(db_url, body)


def test_c15_removing_the_job_piece_cancels_the_job(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        await w.remove(job["piece"])
        await w.ticks(4)
        assert state_of(w.url, job["job"]) == "cancelled" and w.model.asked == []

    scenario(db_url, body)


def test_c15_removing_the_piece_of_a_running_claude_code_job_closes_its_session(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec("claude_code"), can_code=True)
        await w.ticks(3)
        sid = next(iter(w.bridge.sessions_))
        await w.remove(job["piece"])
        await w.ticks(4)
        assert w.bridge.closed == [sid] and state_of(w.url, job["job"]) == "cancelled"

    scenario(db_url, body)


def test_c15_the_job_piece_shows_cancelled_unless_it_was_removed(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        await w.tools().call(call("bench_job_cancel", job=job["job"]))
        await w.ticks(3)
        assert (await body_of_piece(w, job["piece"]))["state"] == "cancelled"
        assert job["piece"] in await w.pieces()

    scenario(db_url, body)


def test_c09_the_runner_retakes_a_lapsed_agent_job_and_finishes_it_at_attempt_two(db_url: str) -> None:
    async def body(w: World) -> None:
        (job,) = await handed(w, spec())
        w.model.script = [calls_of(("bench_add", {"kind": "note", "title": "first", "body": "FIRST-ATTEMPT"})), HANG]
        await w.ticks(4)
        (first_piece,) = made_of(w, job["job"])
        runner_one = w.runners[-1]
        await runner_one.stop() if hasattr(runner_one, "stop") else None
        age(w.url, job["job"], "claimed_at", cfg().claim_s * 10 + 60)
        w.model.script = [finished("carried on", [])]
        w.runner()
        await w.ticks(5)
        stored = row(w.url, job["job"])
        assert stored["state"] == "done" and stored["attempts"] == 2
        assert first_piece in made_of(w, job["job"]) and (await w.pieces())[first_piece].text.body == "FIRST-ATTEMPT"

    scenario(db_url, body)
