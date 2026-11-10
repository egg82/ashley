"""Her `bench_run` takes the language the sandbox runs and gives the run to that language's pod; a language it does not
run is an error result with nothing recorded."""

import json
from typing import Any

from ashley import services
from ashley.inference.model import ToolCall
from ashley.runs.sandbox import Sandbox
from ashley.tools.bench_run import BenchRunTools
from sandbox_languages_support import Bench, Recording, bench, run


def tools(b: Bench) -> BenchRunTools:
    conv, turn = b.turn()
    return BenchRunTools(b.owner.household_id, b.owner.person_id, b.bench, conv, turn)


def go(language: str) -> ToolCall:
    return ToolCall("call-1", "bench_run", {"piece_id": 1, "base_version": 1, "language": language})


def test_it_offers_the_languages_the_sandbox_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with bench(db_url) as b:
            services.register(Sandbox, Recording())
            specs = {spec.name: spec for spec in (await tools(b).catalogue()).specs}
            schema: dict[str, Any] = json.loads(json.dumps(specs["bench_run"].parameters))
            assert schema["properties"]["language"]["enum"] == ["python", "build123d"]

    run(scenario())


def test_a_build123d_run_of_a_piece_reaches_the_sandbox_in_that_language(db_url: str) -> None:
    async def scenario() -> None:
        async with bench(db_url) as b:
            box = Recording()
            services.register(Sandbox, box)
            result = await tools(b).call(go("build123d"))
            assert not result.is_error
            assert [(j.language, j.script) for j in box.jobs] == [("build123d", "box = 1")]
            last = await b.runs.last_on_bench(b.owner.household_id, b.bench)
            assert [r.language for r in last.values()] == ["build123d"]

    run(scenario())


def test_a_language_the_sandbox_does_not_run_is_an_error_result_and_nothing_is_recorded(db_url: str) -> None:
    async def scenario() -> None:
        async with bench(db_url) as b:
            box = Recording(offers=("python",))
            services.register(Sandbox, box)
            result = await tools(b).call(go("build123d"))
            assert result.is_error and box.jobs == []
            assert await b.runs.last_on_bench(b.owner.household_id, b.bench) == {}

    run(scenario())
