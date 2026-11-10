"""The in-app worker of a bench job (`ashley.tools.bench_agent`) over a real database and a scripted model: it is
shown the brief and the pieces its job names and no others, reads only those and what it made, edits and runs only
what it made, records what it makes on the job as it goes, stops when its claim is lost, and ends with the summary and
the pieces it made."""

import json
from dataclasses import replace

from ashley import services
from ashley.errands.bench_jobs import BenchJobs, Job, Named
from ashley.errands.jobs_config import CONFIG
from ashley.inference.model import ToolResults
from ashley.tools import bench_agent
from ashley.workshop.workshop import Workshop
from bench_jobs_support import Jobs, calls, db_url as db_url, jobs_world, migrated_template as migrated_template
from contract.conversations_support import run

SECRET = "never-named-body"


async def claimed(w: Jobs, pieces: tuple[Named, ...]) -> Job:
    store = services.get(BenchJobs)
    await store.start(w.s.new("agent", piece=1, pieces=pieces))
    job = await store.claim("agent", 600)
    assert job is not None
    return job


def shown(w: Jobs) -> str:
    return "\n".join(str(e) for e in w.model.asked[0][1].messages) + "\n" + ",".join(t.name for t in w.model.asked[0][1].tools)


def test_it_is_shown_only_the_pieces_named_and_has_only_the_job_tools(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            named, unnamed = await w.piece("note", "Named", "named-body"), await w.piece("note", "Other", SECRET)
            job = await claimed(w, (Named(named),))
            w.model.script = [bench_agent.JobResult(done=True, summary="s", pieces=[])]
            out = await bench_agent.run(job)
            text = shown(w)
            assert "named-body" in text and "brief" in text and SECRET not in text and "Other" not in text
            assert str(unnamed) not in text.split("Piece")[1] if "Piece" in text else True
            assert {t.name for t in w.model.asked[0][1].tools} == {"bench_read_piece", "bench_add", "bench_add_file",
                                                                   "bench_edit", "bench_run"}
            assert w.model.asked[0][0] == "bench_job" and out.state == "done"
    run(go())


def test_it_reads_what_it_was_given_and_made_and_changes_only_what_it_made(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            named, unnamed = await w.piece("note", "Named", "n"), await w.piece("note", "Other", SECRET)
            job = await claimed(w, (Named(named),))
            made_args = {"kind": "note", "title": "Mine", "body": "m"}
            w.model.script = [
                calls("bench_read_piece", {"piece_id": unnamed}, "a"),
                calls("bench_read_piece", {"piece_id": named}, "b"),
                calls("bench_edit", {"piece_id": named, "base_version": 1, "title": "x", "body": "y"}, "c"),
                calls("bench_run", {"piece_id": named, "base_version": 1, "language": "python"}, "d"),
                calls("bench_remove", {"piece_id": named}, "e"),
                calls("bench_read", {}, "f"),
                calls("bench_add", made_args, "g"),
                bench_agent.JobResult(done=True, summary="did it", pieces=[]),
            ]
            out = await bench_agent.run(job)
            by_call = {r.call_id: r for e in w.model.asked[-1][1].messages if isinstance(e, ToolResults)
                       for r in e.results}
            assert SECRET not in by_call["a"].content and by_call["a"].content.startswith("no_such_piece")
            assert not by_call["b"].is_error
            assert by_call["c"].content.startswith("not_yours") and by_call["d"].content.startswith("not_yours")
            assert by_call["e"].content.startswith("unknown_tool") and by_call["f"].content.startswith("unknown_tool")
            made = json.loads(by_call["g"].content)["piece_id"]
            seen = await services.get(BenchJobs).get(w.s.household, w.s.person, job.id)
            assert seen is not None and seen.made == (made,)
            assert (out.state, out.summary, out.outputs) == ("done", "did it", (made,))
            view = await services.get(Workshop).read(w.owner, w.s.bench)
            assert {p.id: p.text.body for p in view.pieces}[named] == "n"
    run(go())


def test_it_edits_and_runs_a_piece_it_made(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await claimed(w, ())
            w.model.script = [
                calls("bench_add", {"kind": "code", "title": "c", "body": "print(1+2)"}, "a"),
                calls("bench_run", {"piece_id": 1, "base_version": 1, "language": "python"}, "b"),
                bench_agent.JobResult(done=False, summary="half", pieces=[99]),
            ]
            out = await bench_agent.run(job)
            made = (await services.get(BenchJobs).get(w.s.household, w.s.person, job.id))
            assert made is not None and len(made.made) == 1
            assert len(w.run.box.jobs) == 1
            assert (out.state, out.reason, out.outputs) == ("failed", "not_done", made.made)
    run(go())


def test_it_stops_when_its_claim_is_lost_and_a_retake_is_told_what_its_earlier_attempt_made(db_url: str) -> None:
    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await claimed(w, ())
            await services.get(BenchJobs).cancel(w.s.household, w.s.person, job.id)
            out = await bench_agent.run(job)
            assert (out.state, out.reason) == ("cancelled", "stopped") and w.model.asked == []
            await services.get(BenchJobs).start(w.s.new("agent"))
            again = await services.get(BenchJobs).claim("agent", 600)
            assert again is not None
            w.model.script = [bench_agent.JobResult(done=True, summary="s", pieces=[])]
            await bench_agent.run(replace(again, made=(4, 5)))
            assert "earlier attempt" in str(w.model.asked[0][1].messages[0]) and "4, 5" in str(w.model.asked[0][1].messages[0])
    run(go())


def test_a_model_that_cannot_answer_ends_the_job_failed_and_a_loop_without_a_result_does_too(db_url: str) -> None:
    from ashley.inference.inference import InferenceUnavailable

    async def go() -> None:
        async with jobs_world(db_url) as w:
            job = await claimed(w, ())
            w.model.script = [InferenceUnavailable("down")]
            assert (await bench_agent.run(job)).reason == "inference_unavailable"
            config = replace(CONFIG, agent_max_tool_rounds=1)
            w.model.script = [calls("bench_read_piece", {"piece_id": 1}, "a"), calls("bench_read_piece", {"piece_id": 1}, "b")]
            out = await bench_agent.run(job, config)
            assert (out.state, out.reason) == ("failed", "no_result")
    run(go())
