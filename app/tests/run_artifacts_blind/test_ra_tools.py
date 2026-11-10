"""Her `bench_run` and `bench_last_run` carry the run's artifacts by name, type and size (no link: her tools hold no link
key and a link lasts minutes) and the report, only when the run has them, so other results are unchanged."""

import json
from typing import Any

from ashley.inference.model import ToolCall
from ashley.tools.bench_run import BenchRunTools
from contract.conversations_support import scalar
from run_artifacts_support import (GOOD, TYPES, Box, World, check_json, go, measurement, measurements_body, model_output, ran,
                                   report_json, world)

REPORT = report_json(check_json("fit", 2.0, ">=", 1.5, rests_on=["w"]), check_json("guess", 2.0, ">=", 1.5, rests_on=["g"]),
                     check_json("bad", 1.0, ">=", 1.5, rests_on=["w"]))


def tools(w: World, url: str, bench: int) -> BenchRunTools:
    home = w.alana.household_id
    conv = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id", (home,)))
    turn = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) VALUES (%s, %s, 'person', 'run it') "
                      "RETURNING id", (conv, home)))
    return BenchRunTools(home, w.alana.person_id, bench, conv, turn)


async def prepared(w: World) -> tuple[int, int]:
    bench = await w.bench()
    await w.add(bench, "measurements", measurements_body(measurement("w", 30), measurement("g", 5, "guessed")))
    return bench, await w.add(bench, "code", "box = 1")


async def asked(t: BenchRunTools, name: str, piece: int, language: str = "build123d") -> dict[str, Any]:
    args: dict[str, object] = {"piece_id": piece, "base_version": 1, "language": language} if name == "bench_run" else {"piece_id": piece}
    got = await t.call(ToolCall("c-1", name, args))
    assert not got.is_error, got.content
    out: dict[str, Any] = json.loads(got.content)
    return out


def test_her_results_name_the_meshes_by_name_type_and_size_with_no_link(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(REPORT)])) as w:
            bench, piece = await prepared(w)
            t = tools(w, db_url, bench)
            for name in ("bench_run", "bench_last_run"):
                got = await asked(t, name, piece)
                assert {a["name"]: (a["media_type"] if "media_type" in a else a.get("type"), a.get("size_bytes", a.get("size")))
                        for a in got["artifacts"]} == {n: (TYPES[n], len(d)) for n, d in GOOD.items()}
                text = json.dumps(got["artifacts"])
                for word in ("/api/files", "http", "url", "expires", "token", "sha"):
                    assert word not in text

    go(scenario())


def test_her_results_carry_the_report_with_a_verdict_on_each_check(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(REPORT)])) as w:
            bench, piece = await prepared(w)
            t = tools(w, db_url, bench)
            for name in ("bench_run", "bench_last_run"):
                report = (await asked(t, name, piece))["report"]
                assert {c["name"]: c["verdict"] for c in report["checks"]} == {"fit": "pass", "guess": "unconfirmed", "bad": "fail"}
                assert report["triangles"] == 12 and [p["name"] for p in report["parts"]] == ["part1"]

    go(scenario())


def test_a_result_with_no_meshes_or_report_has_neither_key(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None, {})])) as w:
            bench, piece = await prepared(w)
            t = tools(w, db_url, bench)
            for name in ("bench_run", "bench_last_run"):
                got = await asked(t, name, piece)
                assert "artifacts" not in got and "report" not in got

    go(scenario())


def test_a_python_result_is_as_it_was(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([ran(stdout="hi", files={"a.txt": "A"})])) as w:
            bench, piece = await prepared(w)
            t = tools(w, db_url, bench)
            for name in ("bench_run", "bench_last_run"):
                got = await asked(t, name, piece, "python")
                assert "artifacts" not in got and "report" not in got and got["stdout"] == "hi"

    go(scenario())


def test_meshes_without_a_report_show_the_meshes_alone(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            bench, piece = await prepared(w)
            got = await asked(tools(w, db_url, bench), "bench_run", piece)
            assert len(got["artifacts"]) == 3 and "report" not in got

    go(scenario())
