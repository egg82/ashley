"""A bench run's artifacts (`ashley.runs.artifacts.keep`, through `run_piece`) are kept in the object store by their
bytes and recorded on the run; one that is not what its suffix says, or that the store cannot take, is named in `skipped`;
the files sweep names the artifacts of the runs that remain, not of those pruned."""

import hashlib
import struct
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace

from bench_run_support import OK, Box, code, world
from files_support import sync
from ashley import services
from ashley.files.intake import key_of
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.runs import runner
from ashley.runs.artifacts import TYPES, keep
from ashley.runs.model import Artifact, BenchRun, NewRun, Output
from ashley.runs.runs import Runs
from ashley.workshop.commands import Run
from ashley.workshop.file_references import named_keys
from ashley.workshop.model import Owner
from ashley.workshop.run_piece import run_piece
from ashley.workshop.workshop import Workshop
from ashley.workshop import rules as workshop_rules
from ashley.db.database import Database
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

GLB = b"glTF" + struct.pack("<I", 2) + b"\0" * 24
STL = b"\0" * 80 + struct.pack("<I", 2) + b"\x01" * 100
BENCH = NewRun(1, None, None, None, "build123d", "s", bench=BenchRun(1, 1, 1, 1))
CHAT = NewRun(1, 1, 1, "c", "build123d", "s")


def made(files: dict[str, bytes]) -> Output:
    return replace(OK, artifacts=files)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


@asynccontextmanager
async def stored(store: MemoryStore | NullStore) -> AsyncGenerator[None]:
    services.register(ObjectStore, store)
    try:
        yield
    finally:
        services.unregister(ObjectStore)


def test_every_artifact_suffix_the_runner_carries_has_a_type_to_hold_it_to() -> None:
    assert set(TYPES) == set(runner.ARTIFACT_SUFFIXES)


@sync
async def test_artifacts_are_stored_by_their_bytes_under_the_household_and_described() -> None:
    store = MemoryStore()
    async with stored(store):
        output, kept = await keep(BENCH, 7, made({"out/model.glb": GLB, "out/model.stl": STL}))
    assert kept == (Artifact("out/model.glb", sha(GLB), len(GLB), "model/gltf-binary"),
                    Artifact("out/model.stl", sha(STL), len(STL), "model/stl"))
    assert output.artifacts == {} and output.skipped == () and output.stdout == OK.stdout
    assert await store.get(key_of(1, sha(GLB))) == GLB


@sync
async def test_an_artifact_that_is_not_what_its_suffix_says_is_named_skipped_and_the_rest_are_kept() -> None:
    async with stored(MemoryStore()):
        output, kept = await keep(BENCH, 7, replace(made({"a.glb": b"just text", "b.stl": STL, "c.3mf": b"PK\x03\x04"}),
                                                    skipped=("big.stl",)))
    assert [a.name for a in kept] == ["b.stl"] and output.skipped == ("big.stl", "a.glb", "c.3mf")


@sync
async def test_with_the_store_down_no_artifact_is_kept_and_all_are_named_skipped() -> None:
    async with stored(NullStore()):
        output, kept = await keep(BENCH, 7, made({"a.glb": GLB, "b.stl": STL}))
    assert kept == () and output.skipped == ("a.glb", "b.stl") and output.artifacts == {}


@sync
async def test_a_chat_run_keeps_none_and_stores_nothing() -> None:
    store = MemoryStore()
    async with stored(store):
        output, kept = await keep(CHAT, 7, made({"a.glb": GLB}))
    assert kept == () and output.skipped == ("a.glb",) and output.artifacts == {} and await store.keys("") == frozenset()


@sync
async def test_an_output_with_no_artifacts_is_returned_as_it_is() -> None:
    output, kept = await keep(BENCH, 7, OK)
    assert output is OK and kept == ()


def test_run_piece_records_the_artifacts_on_the_run_and_the_sweep_names_them_while_it_remains(db_url: str) -> None:
    alana = owner(db_url)
    store = MemoryStore()
    first, second = made({"out/model.glb": GLB}), made({"out/model.stl": STL})

    async def scenario() -> None:
        async with world(db_url, Box(outputs=[first, second])) as w:
            services.register(Database, w.database)
            try:
                async with stored(store):
                    shop = services.get(Workshop)
                    bench = await shop.open(alana, "b")
                    await shop.apply(alana, bench.id, code(alana))
                    command = Run(code(alana).by, 1, 1, "python")
                    one = await run_piece(alana, bench.id, command)
                    assert one.finished is not None and [a.name for a in one.finished.artifacts] == ["out/model.glb"]
                    named = await named_keys(workshop_rules.load())
                    assert key_of(alana.household_id, sha(GLB)) in named
                    await run_piece(alana, bench.id, command)
                    last = (await services.get(Runs).last_on_bench(alana.household_id, bench.id))[1]
                    assert last.artifacts == (Artifact("out/model.stl", sha(STL), len(STL), "model/stl"),)
                    named = await named_keys(workshop_rules.load())
                    assert key_of(alana.household_id, sha(STL)) in named
                    assert key_of(alana.household_id, sha(GLB)) not in named
            finally:
                services.unregister(Database)

    run(scenario())


def test_a_run_with_no_artifacts_has_an_empty_list(db_url: str) -> None:
    alana = owner(db_url)

    async def scenario() -> None:
        async with world(db_url):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            await run_piece(alana, bench.id, Run(code(alana).by, 1, 1, "python"))
            assert (await services.get(Runs).last_on_bench(alana.household_id, bench.id))[1].artifacts == ()

    run(scenario())

