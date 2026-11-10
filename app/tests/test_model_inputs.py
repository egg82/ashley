"""A model run is handed the bench's STL, 3MF and STEP file pieces: real files, put on the bench as an upload is, reach
the sandbox as binary inputs under their piece ids with an index (`inputs.json`) the CAD helper reads. What does not fit
the language's `input_bytes`, or cannot be read from the store, is named in the index with why; nothing else rides along."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from bench_run_support import OK, RULES, Box, code, world
from ashley import services
from ashley.files import config as files_config
from ashley.files.memory import MemoryStore
from ashley.files.sniff import sniff
from files_support import PDF
from ashley.files.store import ObjectStore
from ashley.runs.config import RunsConfig
from ashley.workshop.bench_file import add_file
from ashley.workshop.model_inputs import InputRefused
from ashley.workshop.commands import Add, Archive, Move, Run
from ashley.workshop.model import By, Owner, Place, Text
from ashley.workshop.run_piece import CONFIG, PieceRun, run_piece
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run

MODELS = Path(__file__).parent / "cad_models"
FILES = files_config.load()
BOTH = ("python", "build123d")
STL, THREEMF, STEP, ASCII_STL, OPEN_STL = "featuretype.STL", "featuretype.3MF", "featuretype.STEP", "multibody.stl", "teapot.stl"
SOLID_HEADED = "idler_riser.STL"


def real(name: str) -> bytes:
    return (MODELS / name).read_bytes()


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


def with_input_bytes(input_bytes: int) -> RunsConfig:
    profile = CONFIG.languages["build123d"]
    return replace(CONFIG, languages={**CONFIG.languages, "build123d": replace(profile, input_bytes=input_bytes)})


async def upload(who: Owner, bench: int, name: str) -> int:
    _, applied = await add_file(who, bench, By(who.person_id), real(name), name, "", RULES)
    assert applied.outcome == "accepted" and applied.piece_id is not None
    return applied.piece_id


async def script_on(who: Owner, bench: int) -> int:
    piece = (await services.get(Workshop).apply(who, bench, code(who))).piece_id
    assert piece is not None
    return piece


async def run_as(who: Owner, bench: int, piece: int, language: str = "build123d", config: RunsConfig = CONFIG,
                 inputs: list[int] | None = None) -> PieceRun:
    got = await run_piece(who, bench, Run(By(who.person_id), piece, 1, language), config=config, inputs=inputs)
    assert got.finished is not None
    return got


@pytest.mark.parametrize("name,media", [(STL, "model/stl"), (THREEMF, "model/3mf"), (STEP, "text/plain"),
                                        (ASCII_STL, "text/plain"),
                                        (SOLID_HEADED, "model/stl")])
def test_the_real_files_are_judged_the_types_the_inputs_expect(name: str, media: str) -> None:
    assert sniff(real(name), "", FILES).media_type == media


def test_a_model_run_gets_each_model_file_under_its_piece_id_and_an_index_of_them(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            services.register(ObjectStore, MemoryStore())
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            names = (STL, THREEMF, STEP, ASCII_STL)
            ids = {name: await upload(alana, bench.id, name) for name in names}
            await services.get(Workshop).apply(alana, bench.id, Add(By(alana.person_id), "note", Text("n", "x"), "small"))
            await run_as(alana, bench.id, script)
            job = box.jobs[0]
            ext = {n: n.rsplit(".", 1)[1].lower() for n in names}
            assert dict(job.inputs) == {f"{ids[n]}.{ext[n]}": real(n) for n in names}
            index = json.loads(job.files["inputs.json"])
            assert index["left_out"] == []
            assert [(i["piece"], i["name"], i["file"], i["size"]) for i in index["items"]] == [
                (ids[n], n, f"inputs/{ids[n]}.{ext[n]}", len(real(n))) for n in names]
            services.unregister(ObjectStore)

    run(scenario())


def test_only_model_files_are_handed_over_and_in_the_order_the_bench_lays_them_out(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            services.register(ObjectStore, MemoryStore())
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            _, pdf = await add_file(alana, bench.id, By(alana.person_id), PDF, "drawing.stl", "", RULES)
            _, text = await add_file(alana, bench.id, By(alana.person_id), b"notes", "notes.txt", "", RULES)
            step, threemf = await upload(alana, bench.id, STEP), await upload(alana, bench.id, THREEMF)
            assert pdf.outcome == text.outcome == "accepted"
            await services.get(Workshop).apply(alana, bench.id, Move(By(alana.person_id), threemf, Place(0, "small")))
            await run_as(alana, bench.id, script)
            index = json.loads(box.jobs[0].files["inputs.json"])
            assert [i["piece"] for i in index["items"]] == [threemf, step] and index["left_out"] == []
            services.unregister(ObjectStore)

    run(scenario())


def test_a_shelved_model_a_python_run_and_a_bench_without_models_get_no_inputs(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            services.register(ObjectStore, MemoryStore())
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            await run_as(alana, bench.id, script)
            held = await upload(alana, bench.id, STL)
            await services.get(Workshop).apply(alana, bench.id, Archive(By(alana.person_id), held))
            await run_as(alana, bench.id, script)
            await upload(alana, bench.id, STL)
            await run_as(alana, bench.id, script, "python")
            assert len(box.jobs) == 3
            for job in box.jobs:
                assert dict(job.inputs) == {} and "inputs.json" not in job.files
            services.unregister(ObjectStore)

    run(scenario())


def test_what_exceeds_input_bytes_is_left_out_by_name_and_the_rest_is_still_given(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)
    room = len(real(THREEMF)) + len(real(OPEN_STL))

    async def scenario() -> None:
        async with world(db_url, box):
            services.register(ObjectStore, MemoryStore())
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            big = await upload(alana, bench.id, STEP)
            small = await upload(alana, bench.id, THREEMF)
            fits = await upload(alana, bench.id, OPEN_STL)
            await run_as(alana, bench.id, script, config=with_input_bytes(room))
            index = json.loads(box.jobs[0].files["inputs.json"])
            assert sorted(box.jobs[0].inputs) == sorted([f"{fits}.stl", f"{small}.3mf"])
            assert index["left_out"] == [{"piece": big, "name": STEP, "why": "too_large"}]
            services.unregister(ObjectStore)

    run(scenario())


def test_a_model_the_store_cannot_give_is_left_out_as_unavailable(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            store = MemoryStore()
            services.register(ObjectStore, store)
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            held = await upload(alana, bench.id, STL)
            store.down = True
            await run_as(alana, bench.id, script)
            assert dict(box.jobs[0].inputs) == {}
            assert json.loads(box.jobs[0].files["inputs.json"])["left_out"] == [
                {"piece": held, "name": STL, "why": "unavailable"}]
            services.unregister(ObjectStore)

    run(scenario())


def test_the_last_runs_index_is_not_carried_into_the_next_run(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[replace(OK, files={"inputs.json": "stale", "state.txt": "1"})], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            services.register(ObjectStore, MemoryStore())
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            await run_as(alana, bench.id, script)
            await run_as(alana, bench.id, script)
            assert "inputs.json" not in box.jobs[1].files and box.jobs[1].files["state.txt"] == "1"
            services.unregister(ObjectStore)

    run(scenario())


def test_a_run_naming_its_inputs_is_given_only_those_and_the_others_are_not_in_the_index(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            services.register(ObjectStore, MemoryStore())
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            first, second = await upload(alana, bench.id, STL), await upload(alana, bench.id, THREEMF)
            await run_as(alana, bench.id, script, inputs=[second])
            await run_as(alana, bench.id, script, inputs=[])
            await run_as(alana, bench.id, script)
            named, none, everything = box.jobs
            assert list(named.inputs) == [f"{second}.3mf"]
            index = json.loads(named.files["inputs.json"])
            assert [i["piece"] for i in index["items"]] == [second] and index["left_out"] == []
            assert dict(none.inputs) == {} and "inputs.json" not in none.files
            assert sorted(everything.inputs) == sorted([f"{first}.stl", f"{second}.3mf"])
            services.unregister(ObjectStore)

    run(scenario())


def test_the_size_limit_counts_only_the_named_inputs(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)
    room = len(real(STEP)) + len(real(THREEMF)) - 1

    async def scenario() -> None:
        async with world(db_url, box):
            services.register(ObjectStore, MemoryStore())
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            await upload(alana, bench.id, STEP)
            wanted = await upload(alana, bench.id, THREEMF)
            await run_as(alana, bench.id, script, config=with_input_bytes(room), inputs=[wanted])
            assert list(box.jobs[0].inputs) == [f"{wanted}.3mf"]
            services.unregister(ObjectStore)

    run(scenario())


async def refused(who: Owner, bench: int, piece: int, inputs: list[int], config: RunsConfig = CONFIG) -> InputRefused:
    with pytest.raises(InputRefused) as caught:
        await run_piece(who, bench, Run(By(who.person_id), piece, 1, "build123d"), config=config, inputs=inputs)
    return caught.value


def test_a_named_input_that_cannot_be_given_refuses_the_run_naming_it_and_nothing_runs(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[OK], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            store = MemoryStore()
            services.register(ObjectStore, store)
            bench = await services.get(Workshop).open(alana, "b")
            script = await script_on(alana, bench.id)
            _, text = await add_file(alana, bench.id, By(alana.person_id), b"notes", "notes.txt", "", RULES)
            assert text.piece_id is not None
            gone = await upload(alana, bench.id, STL)
            await services.get(Workshop).apply(alana, bench.id, Archive(By(alana.person_id), gone))
            big, small = await upload(alana, bench.id, STEP), await upload(alana, bench.id, THREEMF)
            assert (await refused(alana, bench.id, script, [999])).why == "missing"
            assert (await refused(alana, bench.id, script, [gone])).why == "missing"
            not_model = await refused(alana, bench.id, script, [text.piece_id])
            assert (not_model.piece, not_model.why) == (text.piece_id, "not_model")
            tight = with_input_bytes(len(real(THREEMF)))
            over = await refused(alana, bench.id, script, [small, big], tight)
            assert (over.piece, over.why) == (big, "too_large")
            assert over.sizes == f"{len(real(STEP))} bytes against {len(real(THREEMF))}"
            assert over.sizes == f"{len(real(STEP))} bytes against {len(real(THREEMF))}"
            store.down = True
            assert (await refused(alana, bench.id, script, [small])).why == "unavailable"
            assert box.jobs == []
            services.unregister(ObjectStore)

    run(scenario())
