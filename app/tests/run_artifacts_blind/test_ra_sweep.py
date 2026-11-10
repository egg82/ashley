"""A run's meshes are named by the runs that remain: pruning a run releases them, and the orphan sweep never deletes one a
remaining run still names."""

from datetime import timedelta

from ashley.files import sweep
from ashley.files.intake import key_of
from ashley.files.mirror import MirroredStore
from ashley.files.orphans import PostgresCandidates
from ashley.runs.model import Output
from ashley.workshop.file_references import named_keys
from ashley.workshop.run_piece import run_piece
from run_artifacts_support import CONFIG, GLB_NAME, Box, Site, glb, go, model_output, run_cmd, sha, world

GRACE = timedelta(seconds=CONFIG.sweep_grace_s)


def mesh(tag: str) -> bytes:
    return glb(tag.encode() * 4)


def test_the_meshes_of_a_run_that_remains_are_named(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None, {GLB_NAME: mesh("a")})])) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            assert key_of(w.alana.household_id, sha(mesh("a"))) in await named_keys(w.rules)

    go(scenario())


def test_the_meshes_of_both_households_are_named(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None, {GLB_NAME: mesh("a")})])) as w:
            for owner in (w.alana, w.zed):
                bench = await w.bench(owner)
                piece = await w.add(bench, "code", "box = 1", owner)
                await run_piece(owner, bench, run_cmd(owner, piece))
            named = await named_keys(w.rules)
            assert {key_of(w.alana.household_id, sha(mesh("a"))), key_of(w.zed.household_id, sha(mesh("a")))} <= named

    go(scenario())


def test_pruning_a_run_releases_its_meshes_and_only_its_own(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None, {GLB_NAME: mesh("a")}), model_output(None, {GLB_NAME: mesh("b")})])) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            first = (await run_piece(w.alana, bench, run_cmd(w.alana, piece))).finished
            assert first is not None
            home = w.alana.household_id
            assert key_of(home, sha(mesh("a"))) in await named_keys(w.rules)
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            named = await named_keys(w.rules)
            assert await w.runs.get(home, first.run_id) is None
            assert key_of(home, sha(mesh("a"))) not in named and key_of(home, sha(mesh("b"))) in named

    go(scenario())


def test_the_latest_run_that_ran_to_its_end_keeps_its_meshes_after_a_later_failure(db_url: str) -> None:
    async def scenario() -> None:
        failed = Output("failed", None, "", "", False, {}, ())
        async with world(db_url, Box([model_output(None, {GLB_NAME: mesh("a")}), failed, failed])) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            for _ in range(3):
                await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            assert key_of(w.alana.household_id, sha(mesh("a"))) in await named_keys(w.rules)

    go(scenario())


def test_the_sweep_keeps_every_referenced_mesh_and_removes_only_the_released_one(db_url: str) -> None:
    async def scenario() -> None:
        site = Site()
        plays = [model_output(None, {GLB_NAME: mesh(t)}) for t in ("a", "a", "b")]
        async with world(db_url, Box(plays), site) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            other_bench = await w.bench(w.zed)
            other_piece = await w.add(other_bench, "code", "box = 1", w.zed)
            home = w.alana.household_id
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            await run_piece(w.zed, other_bench, run_cmd(w.zed, other_piece))
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            released, kept_key = key_of(home, sha(mesh("a"))), key_of(home, sha(mesh("b")))
            zed_key = key_of(w.zed.household_id, sha(mesh("a")))
            assert {released, kept_key, zed_key} <= set(site.held)
            mirror = MirroredStore([site])
            clock = site.now + GRACE * 5
            for _ in range(4):
                await sweep.run_once(mirror, lambda: named_keys(w.rules), PostgresCandidates(), CONFIG, lambda: clock)
            assert released not in site.held
            assert kept_key in site.held and zed_key in site.held

    go(scenario())


def test_the_sweep_never_deletes_a_mesh_a_remaining_run_names_however_many_passes(db_url: str) -> None:
    async def scenario() -> None:
        site = Site()
        async with world(db_url, Box([model_output(None)]), site) as w:
            bench = await w.bench()
            piece = await w.add(bench, "code", "box = 1")
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            held = dict(site.held)
            assert len(held) == 3
            clock = site.now + GRACE * 50
            for _ in range(6):
                await sweep.run_once(MirroredStore([site]), lambda: named_keys(w.rules), PostgresCandidates(), CONFIG,
                                     lambda: clock)
            assert site.held == held

    go(scenario())
