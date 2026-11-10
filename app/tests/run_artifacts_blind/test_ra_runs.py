"""A bench run's meshes through `run_once` and the Runs record: kept in the object store, recorded in `code_runs.artifacts`
as name, hash, size and type, never as bytes; a chat run keeps none; a store that is down costs the meshes and not the run."""

import base64
import json
from typing import Any

import psycopg
from ashley.files.intake import key_of
from ashley.runs.model import Artifact, BenchRun, NewRun, Output
from ashley.runs.once import run_once
from ashley.workshop.run_piece import run_piece
from run_artifacts_support import (CAD, GLB_NAME, GOOD, MF_NAME, STL_NAME, TYPES, Box, Site, ran, glb, go, model_output, run_cmd,
                                   sha, stl, threemf, world)


def row_json(url: str, run_id: int) -> str:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT row_to_json(r)::text FROM code_runs r WHERE id = %s", (run_id,)).fetchone()
    assert row is not None
    return str(row[0])


def column(url: str, run_id: int) -> Any:
    with psycopg.connect(url, autocommit=True) as conn:
        row = conn.execute("SELECT artifacts::text FROM code_runs WHERE id = %s", (run_id,)).fetchone()
    assert row is not None
    return json.loads(row[0])


def test_a_bench_run_keeps_its_meshes_and_records_what_it_kept(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece))).finished
            assert done is not None and done.reached
            assert {a.name: (a.sha256, a.size, a.media_type) for a in done.artifacts} == {
                n: (sha(d), len(d), TYPES[n]) for n, d in GOOD.items()}
            assert dict(done.output.artifacts) == {}
            assert set(w.store.held) == {key_of(w.alana.household_id, sha(d)) for d in GOOD.values()}
            stored = await w.runs.get(w.alana.household_id, done.run_id)
            assert stored is not None and stored.artifacts == done.artifacts
            assert dict(stored.output.artifacts if stored.output else {"x": b""}) == {}
            [last] = (await w.runs.last_on_bench(w.alana.household_id, bench)).values()
            assert last.artifacts == done.artifacts
            recorded: list[dict[str, Any]] = column(db_url, done.run_id)
            assert sorted(recorded, key=lambda e: e["name"]) == sorted(
                ({"name": a.name, "sha256": a.sha256, "size": a.size, "media_type": a.media_type} for a in done.artifacts),
                key=lambda e: e["name"])

    go(scenario())


def test_the_bytes_of_a_mesh_are_nowhere_in_the_runs_row(db_url: str) -> None:
    async def scenario() -> None:
        marker = b"UNIQUE-MARKER-QZX-" * 3
        mesh = glb(marker)
        async with world(db_url, Box([model_output(None, {GLB_NAME: mesh})])) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece))).finished
            assert done is not None and [a.name for a in done.artifacts] == [GLB_NAME]
            row = row_json(db_url, done.run_id)
            assert "UNIQUE-MARKER" not in row and base64.b64encode(marker)[:12].decode() not in row
            assert marker.hex()[:20] not in row

    go(scenario())


def test_a_chat_run_keeps_no_mesh(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            done = await run_once(w.chat_run())
            assert done.reached and done.artifacts == () and w.store.held == {}
            stored = await w.runs.get(w.alana.household_id, done.run_id)
            assert stored is not None and stored.artifacts == ()

    go(scenario())


def test_a_run_with_no_meshes_records_none(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([ran(files={"a.txt": "A"})])) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "x = 1")
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece, language="python"))).finished
            assert done is not None and done.artifacts == () and w.store.calls.log == []
            stored = await w.runs.get(w.alana.household_id, done.run_id)
            assert stored is not None and stored.artifacts == ()

    go(scenario())


def test_a_store_that_is_down_costs_the_meshes_and_not_the_run(db_url: str) -> None:
    async def scenario() -> None:
        site = Site()
        site.down = True
        async with world(db_url, Box([model_output("{}")]), site) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece))).finished
            assert done is not None and done.reached and done.artifacts == ()
            assert set(GOOD) <= set(done.output.skipped)
            stored = await w.runs.get(w.alana.household_id, done.run_id)
            assert stored is not None and stored.output is not None and stored.finished_at is not None
            assert stored.artifacts == () and set(GOOD) <= set(stored.output.skipped)

    go(scenario())


def test_a_mesh_that_is_not_what_its_suffix_says_is_skipped_in_the_record(db_url: str) -> None:
    async def scenario() -> None:
        wrong = {GLB_NAME: stl(2), STL_NAME: stl(2), MF_NAME: threemf()}
        async with world(db_url, Box([model_output(None, wrong)])) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece))).finished
            assert done is not None and {a.name for a in done.artifacts} == {STL_NAME, MF_NAME}
            assert GLB_NAME in done.output.skipped
            stored = await w.runs.get(w.alana.household_id, done.run_id)
            assert stored is not None and stored.output is not None and GLB_NAME in stored.output.skipped

    go(scenario())


def test_runs_finish_records_given_artifacts_and_drops_the_output_bytes(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.chat_run())
            art = Artifact(GLB_NAME, sha(GOOD[GLB_NAME]), len(GOOD[GLB_NAME]), "model/gltf-binary")
            done = await w.runs.finish(run_id, Output("ran", 0, "o", "", False, {}, (), {GLB_NAME: b"RAW-BYTES-HERE"}), [art])
            assert done.artifacts == (art,)
            assert dict(done.output.artifacts if done.output else {"x": b""}) == {}
            assert "RAW-BYTES-HERE" not in row_json(db_url, run_id)
            other = await w.runs.get(w.zed.household_id, run_id)
            assert other is None

    go(scenario())


def test_a_run_not_yet_finished_has_no_artifacts(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            run_id = await w.runs.start(w.chat_run())
            started = await w.runs.get(w.alana.household_id, run_id)
            assert started is not None and started.artifacts == ()

    go(scenario())


def test_a_run_that_finishes_after_a_later_one_is_still_there_with_its_meshes(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            home = w.alana.household_id
            seqs = [(await w.workshop.apply(w.alana, bench, run_cmd(w.alana, piece))).seq for _ in range(2)]
            early, late = [await w.runs.start(NewRun(home, None, None, None, CAD, "box = 1", "", {}, BenchRun(bench, s, piece, 1)))
                           for s in seqs]
            await w.runs.finish(late, ran(), [])
            art = Artifact(GLB_NAME, sha(GOOD[GLB_NAME]), len(GOOD[GLB_NAME]), "model/gltf-binary")
            await w.runs.finish(early, ran(), [art])
            kept = await w.runs.get(home, early)
            assert kept is not None and kept.artifacts == (art,)

    go(scenario())
