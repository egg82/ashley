"""`run_files` brings a piece's latest run's kept text files and the binary artifacts it made (a model run's STL, 3MF and
GLB), named `p<piece>-<stem>.<ext>`; an artifact counts against the job's byte cap, one the store lost fails the job
with `file_missing`, and a file the run could not keep is named in `p<piece>-skipped.txt`."""

import struct
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from bjb_support import MARK_BRIEF, World, bench_session, named, scenario
from ashley import services
from ashley.errands import jobs_config
from ashley.files.intake import key_of
from ashley.runs.model import Output
from ashley.runs.runs import Runs
from ashley.tools import bench_job_start
from ashley.tools.bench_job_args import Draft
from ashley.workshop.commands import Run
from ashley.workshop.model import By
from ashley.workshop.run_piece import run_piece
from bench_run_support import Box

STL = b"\x00" * 80 + struct.pack("<I", 2) + bytes(range(1, 101))
STL2 = b"\x00" * 80 + struct.pack("<I", 1) + bytes(range(1, 51))
GLB = b"glTF" + struct.pack("<I", 2) + struct.pack("<I", 15) + b"one"


def made(artifacts: Mapping[str, bytes], skipped: tuple[str, ...] = ()) -> Output:
    return Output("ran", 0, "", "", False, {"print.json": "{}"}, skipped, dict(artifacts))


async def model_run(w: World, output: Output) -> int:
    """A model piece whose latest run gave `output`; the piece id."""
    box: Box = w.ran.box
    box.offered = ("python", "build123d")
    box.outputs = [output]
    piece = await w.piece("model", "holder", "box = 1")
    done = await run_piece(w.owner, w.bench, Run(By(w.owner.person_id), piece, 1, "build123d"))
    assert done.finished is not None, done
    return piece


async def claude_job(w: World, pieces: list[Any]) -> Any:
    await w.started("claude_code", pieces=pieces, brief=MARK_BRIEF)
    return await w.claimed("claude_code")


async def fresh(w: World, job: Any) -> Any:
    return await w.jobs.get(w.owner.household_id, w.owner.person_id, job.id)


def only_session(w: World) -> str:
    (sid,) = w.bridge.sessions_
    return sid


async def sent_by_a_job(w: World, piece: int) -> dict[str, bytes]:
    job = await claude_job(w, [named(piece, True)])
    await bench_session.step(await fresh(w, job))
    return w.bridge.inbox[only_session(w)]


def test_run_files_on_a_model_piece_bring_the_runs_artifacts(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await model_run(w, made({"out/model.stl": STL, "out/model.glb": GLB}))
        sent = await sent_by_a_job(w, piece)
        assert sent[f"p{piece}-model.stl"] == STL and sent[f"p{piece}-model.glb"] == GLB
        assert f"p{piece}.py" in sent and f"p{piece}-run.json" in sent

    scenario(db_url, body)


def test_artifact_names_come_from_the_file_never_the_title_and_stay_unique(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await model_run(w, made({"out/a.stl": STL, "b/a.stl": STL2, "out/we ird!.glb": GLB}))
        sent = await sent_by_a_job(w, piece)
        artifacts = {n for n in sent if n.endswith((".stl", ".glb"))}
        assert len(artifacts) == 3 and all(n.startswith(f"p{piece}-") for n in artifacts)
        assert "holder" not in " ".join(sent)

    scenario(db_url, body)


def test_without_run_files_no_artifact_goes(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await model_run(w, made({"out/model.stl": STL}))
        job = await claude_job(w, [named(piece, False)])
        await bench_session.step(await fresh(w, job))
        assert set(w.bridge.inbox[only_session(w)]) == {f"p{piece}.py"}

    scenario(db_url, body)


def test_artifacts_count_against_the_bytes_a_job_is_given(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await model_run(w, made({"out/model.stl": STL}))
        tight = replace(jobs_config.load(), max_bytes_in=len(STL) + 2)
        owner = w.owner
        draft = Draft("claude_code", "t", "b", (named(piece, True),))
        try:
            await bench_job_start.check(owner, w.bench, (draft,), tight)
        except bench_job_start.Refused as e:
            assert e.reason == "too_large"
        else:
            raise AssertionError("an artifact over the cap was accepted")
        await bench_job_start.check(owner, w.bench, (Draft("claude_code", "t", "b", (named(piece, False),)),), tight)

    scenario(db_url, body)


def test_an_artifact_the_store_lost_fails_the_job_as_file_missing(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await model_run(w, made({"out/model.stl": STL}))
        run = (await services.get(Runs).last_on_bench(w.owner.household_id, w.bench))[piece]
        (artifact,) = run.artifacts
        del w.store.objects[key_of(w.owner.household_id, artifact.sha256)]
        job = await claude_job(w, [named(piece, True)])
        out = await bench_session.step(await fresh(w, job))
        assert out is not None and out.reason == "file_missing"

    scenario(db_url, body)


def test_what_the_run_could_not_keep_is_named_in_a_skipped_file(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await model_run(w, made({"out/model.stl": STL}, skipped=("out/model.3mf",)))
        sent = await sent_by_a_job(w, piece)
        assert b"out/model.3mf" in sent[f"p{piece}-skipped.txt"]

    scenario(db_url, body)


def test_a_run_that_skipped_nothing_has_no_skipped_file(db_url: str) -> None:
    async def body(w: World) -> None:
        piece = await model_run(w, made({"out/model.stl": STL}))
        assert f"p{piece}-skipped.txt" not in await sent_by_a_job(w, piece)

    scenario(db_url, body)

