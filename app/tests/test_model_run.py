"""A model run (language `build123d`) over a real database: it starts with the bench's measurements merged as
`measurements.json`, the shipped print settings as `print.json`, and without the last run's stale report; its artifacts and report come back on the wire
(`piece_run_of`) with download links, and to her (`bench_run`, `bench_last_run`); a Python run gets none of that."""

import json
import struct
from dataclasses import replace
from typing import Any

from bench_run_support import OK, Box, code, world
from ashley import services
from ashley.api.bench_run_models import piece_run_of
from ashley.files import links
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.inference.model import ToolCall
from ashley.runs.runs import Runs
from ashley.tools.bench_run import BenchRunTools
from ashley.workshop import print_file
from ashley.workshop.commands import Add, Archive, Run
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.run_piece import run_piece
from ashley.workshop.workshop import Workshop
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run, scalar

KEY = b"k" * 32
GLB = b"glTF" + struct.pack("<I", 2) + b"\0" * 24
BOTH = ("python", "build123d")


def item(name: str, value: float, source: str = "measured") -> dict[str, Any]:
    return {"name": name, "value": value, "unit": "mm", "source": source}


def measuring(owner: Owner, *items: dict[str, Any]) -> Add:
    return Add(By(owner.person_id), "measurements", Text("m", json.dumps({"items": list(items)})), "small")


REPORT = {"unit": "mm", "parts": [{"name": "lid", "volume": 9.0, "bbox": {"min": [0, 0, 0], "max": [4, 3, 1]}}],
          "triangles": 12, "checks": [{"name": "fit", "actual": 2.0, "op": ">=", "target": 1.5, "tolerance": 0.0,
                                       "rests_on": ["board"]}]}
MODEL = replace(OK, files={"out/report.json": json.dumps(REPORT), "measurements.json": "stale", "print.json": "stale"},
                artifacts={"out/model.glb": GLB})


def owner(url: str) -> Owner:
    home = household(url)
    return Owner(home, person(url, home))


def test_a_model_run_starts_with_the_current_measurements_and_no_stale_report_and_a_python_run_with_neither(
        db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[MODEL], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            await shop.apply(alana, bench.id, measuring(alana, item("board", 30), item("gap", 1.5, "guessed")))
            await shop.apply(alana, bench.id, measuring(alana, item("board", 99), item("hole", 4)))
            await shop.apply(alana, bench.id, measuring(alana, item("shelved", 1)))
            await shop.apply(alana, bench.id, Archive(By(alana.person_id), 4))
            await shop.apply(alana, bench.id, Add(By(alana.person_id), "note", Text("n", json.dumps({"items": [item("note_only", 7)]})), "small"))
            services.register(ObjectStore, MemoryStore())
            try:
                first = await run_piece(alana, bench.id, Run(By(alana.person_id), 1, 1, "build123d"))
                second = await run_piece(alana, bench.id, Run(By(alana.person_id), 1, 1, "build123d"))
                third = await run_piece(alana, bench.id, Run(By(alana.person_id), 1, 1, "python"))
            finally:
                services.unregister(ObjectStore)
            assert first.finished is not None and second.finished is not None and third.finished is not None
            merged = json.loads(box.jobs[0].files["measurements.json"])
            assert [i["name"] for i in merged["items"]] == ["board", "gap", "hole"]
            assert merged["items"][0]["value"] == 30
            assert "out/report.json" not in box.jobs[1].files and box.jobs[1].files["measurements.json"] != "stale"
            assert json.loads(box.jobs[1].files["print.json"]) == json.loads(print_file.FILE.read_text())
            assert dict(box.jobs[2].files) == dict(MODEL.files)

    run(scenario())


def test_a_model_run_on_a_bench_without_measurements_is_given_no_measurements_file(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[MODEL], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            services.register(ObjectStore, MemoryStore())
            try:
                await run_piece(alana, bench.id, Run(By(alana.person_id), 1, 1, "build123d"))
                await run_piece(alana, bench.id, Run(By(alana.person_id), 1, 1, "build123d"))
            finally:
                services.unregister(ObjectStore)
            assert box.jobs[0].files == {"print.json": print_file.file_text()} and "measurements.json" not in box.jobs[1].files
            assert "out/report.json" not in box.jobs[1].files

    run(scenario())


def test_the_wire_carries_the_artifacts_with_links_and_the_report_with_its_verdicts(db_url: str) -> None:
    alana = owner(db_url)
    box = Box(outputs=[MODEL], offered=BOTH)

    async def scenario() -> None:
        async with world(db_url, box):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            await shop.apply(alana, bench.id, measuring(alana, item("board", 30, "guessed")))
            services.register(ObjectStore, MemoryStore())
            try:
                await run_piece(alana, bench.id, Run(By(alana.person_id), 1, 1, "build123d"))
            finally:
                services.unregister(ObjectStore)
            last = (await services.get(Runs).last_on_bench(alana.household_id, bench.id))[1]
            out = piece_run_of(last, KEY).run_output
            assert out is not None and out.report is not None
            assert [(c.name, c.verdict) for c in out.report.checks] == [("fit", "unconfirmed")]
            assert (out.report.parts[0].bbox_max, out.report.triangles) == ([4.0, 3.0, 1.0], 12)
            (artifact,) = out.artifacts
            assert (artifact.name, artifact.media_type, artifact.size_bytes) == ("out/model.glb", "model/gltf-binary", len(GLB))
            assert artifact.url is not None and artifact.url.startswith(links.PATH)
            grant = links.check(KEY, artifact.url[len(links.PATH):], 0)
            assert grant is not None and (grant.household_id, grant.media_type, grant.inline) == (
                alana.household_id, "model/gltf-binary", False)
            bare = piece_run_of(last).run_output
            assert bare is not None and bare.artifacts[0].url is None and bare.artifacts[0].expires_at is None

    run(scenario())


def test_a_run_with_neither_has_no_artifacts_and_no_report_on_the_wire_and_in_her_results(db_url: str) -> None:
    alana = owner(db_url)
    conversation = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (alana.household_id,)))
    said = int(scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                              "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conversation, alana.household_id)))

    async def scenario() -> None:
        async with world(db_url, Box(outputs=[OK], offered=BOTH)):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            tools = BenchRunTools(alana.household_id, alana.person_id, bench.id, conversation, said)
            got = json.loads((await tools.call(ToolCall("c1", "bench_run", {"piece_id": 1, "base_version": 1,
                                                                            "language": "python"}))).content)
            assert "artifacts" not in got and "report" not in got
            last = (await services.get(Runs).last_on_bench(alana.household_id, bench.id))[1]
            out = piece_run_of(last, KEY).run_output
            assert out is not None and out.artifacts == [] and out.report is None

    run(scenario())


def test_her_results_carry_a_model_runs_artifacts_by_name_and_its_report_with_verdicts(db_url: str) -> None:
    alana = owner(db_url)
    conversation = int(scalar(db_url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (alana.household_id,)))
    said = int(scalar(db_url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                              "VALUES (%s, %s, 'person', 'run it') RETURNING id", (conversation, alana.household_id)))

    async def scenario() -> None:
        async with world(db_url, Box(outputs=[MODEL], offered=BOTH)):
            shop = services.get(Workshop)
            bench = await shop.open(alana, "b")
            await shop.apply(alana, bench.id, code(alana))
            await shop.apply(alana, bench.id, measuring(alana, item("board", 30)))
            services.register(ObjectStore, MemoryStore())
            try:
                tools = BenchRunTools(alana.household_id, alana.person_id, bench.id, conversation, said)
                args = {"piece_id": 1, "base_version": 1, "language": "build123d"}
                ran = json.loads((await tools.call(ToolCall("c1", "bench_run", args))).content)
                last = json.loads((await tools.call(ToolCall("c2", "bench_last_run", {"piece_id": 1}))).content)
            finally:
                services.unregister(ObjectStore)
            for body in (ran, last):
                assert body["artifacts"] == [{"name": "out/model.glb", "media_type": "model/gltf-binary",
                                              "size_bytes": len(GLB)}]
                assert [(c["name"], c["verdict"]) for c in body["report"]["checks"]] == [("fit", "pass")]
                assert "http" not in json.dumps(body["artifacts"]) and "/api/files" not in json.dumps(body["artifacts"])

    run(scenario())
