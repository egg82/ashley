"""What a model run starts with: the bench's facts pieces (not shelved, layout order) merged as `facts.json`,
recorded with the run, and without the last run's `facts.json` and `out/report.json`; a Python run's files are
untouched."""

import json

from ashley.workshop.run_piece import run_piece
from run_artifacts_support import Box, World, go, measurement, facts_body, model_output, ran, run_cmd, world

STALE = {"facts.json": "OLD", "out/report.json": "{}", "keep.txt": "K"}


async def measured_bench(w: World, *bodies: str) -> tuple[int, int]:
    bench = await w.bench()
    for body in bodies:
        await w.add(bench, "facts", body)
    piece = await w.add(bench, "code", "box = 1")
    return bench, piece


def measurement_items(text: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = json.loads(text)["items"]
    return items


def test_a_model_run_starts_with_the_benchs_facts_merged_and_records_them(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            first, second = measurement("w", 30), measurement("d", 4, "datasheet")
            bench, piece = await measured_bench(w, facts_body(first), facts_body(second))
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece))).finished
            assert done is not None
            [job] = w.box.jobs
            assert job.language == "build123d" and measurement_items(job.files["facts.json"]) == [first, second]
            assert dict(done.inputs) == dict(job.files)
            stored = await w.runs.get(w.alana.household_id, done.run_id)
            assert stored is not None and stored.files["facts.json"] == job.files["facts.json"]

    go(scenario())


def test_a_name_a_later_piece_repeats_keeps_the_first_value_in_the_run(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            bench, piece = await measured_bench(w, facts_body(measurement("w", 30)),
                                                facts_body(measurement("w", 99, "guessed")))
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            assert measurement_items(w.box.jobs[0].files["facts.json"]) == [measurement("w", 30)]

    go(scenario())


def test_a_shelved_facts_piece_is_left_out(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            bench = await w.bench()
            kept = await w.add(bench, "facts", facts_body(measurement("a", 1)))
            shelved = await w.add(bench, "facts", facts_body(measurement("b", 2)))
            piece = await w.add(bench, "code", "box = 1")
            await w.shelve(bench, shelved)
            assert kept != shelved
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            assert [i["name"] for i in measurement_items(w.box.jobs[0].files["facts.json"])] == ["a"]

    go(scenario())


def test_a_bench_with_no_facts_gives_the_run_no_file(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            bench, piece = await measured_bench(w)
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece))).finished
            assert done is not None and "facts.json" not in w.box.jobs[0].files
            assert "facts.json" not in done.inputs

    go(scenario())


def test_only_this_benchs_facts_are_used(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([model_output(None)])) as w:
            await measured_bench(w, facts_body(measurement("elsewhere", 1)))
            bench, piece = await measured_bench(w, facts_body(measurement("here", 2)))
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            assert [i["name"] for i in measurement_items(w.box.jobs[0].files["facts.json"])] == ["here"]

    go(scenario())


def test_the_last_runs_facts_and_report_are_not_carried_into_the_next_model_run(db_url: str) -> None:
    async def scenario() -> None:
        first = ran(files=STALE, artifacts={})
        async with world(db_url, Box([first, model_output(None)])) as w:
            bench, piece = await measured_bench(w, facts_body(measurement("w", 30)))
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            files = w.box.jobs[1].files
            assert "out/report.json" not in files and files["keep.txt"] == "K"
            assert measurement_items(files["facts.json"]) == [measurement("w", 30)]

    go(scenario())


def test_a_model_run_with_no_facts_does_not_inherit_the_old_file(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([ran(files=STALE), model_output(None)])) as w:
            bench, piece = await measured_bench(w)
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            await run_piece(w.alana, bench, run_cmd(w.alana, piece))
            files = w.box.jobs[1].files
            assert "facts.json" not in files and "out/report.json" not in files and files["keep.txt"] == "K"

    go(scenario())


def test_a_python_runs_files_are_untouched(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url, Box([ran(files=STALE), ran()])) as w:
            bench, piece = await measured_bench(w, facts_body(measurement("w", 30)))
            await run_piece(w.alana, bench, run_cmd(w.alana, piece, language="python"))
            done = (await run_piece(w.alana, bench, run_cmd(w.alana, piece, language="python"))).finished
            assert done is not None
            assert dict(w.box.jobs[0].files) == {} and dict(w.box.jobs[1].files) == STALE
            assert dict(done.inputs) == STALE

    go(scenario())
