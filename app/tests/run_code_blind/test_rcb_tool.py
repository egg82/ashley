"""The run_code tool: offered only when a sandbox runs something, recorded before and after, run once, and never
raising."""

import json
from typing import Any

import pytest
from ashley import services
from ashley.inference.model import ToolCall
from ashley.runs.model import Job, Outcome, Output
from ashley.runs.runs import Runs
from ashley.runs.sandbox import Sandbox
from rcb_support import run
from rcb_tool import GIVES, Recording, Unavailable, Wrapped, tools
from rcb_world import World, other_household, world


def call(script: Any = "print(1)", language: Any = "python", id: str = "call-1", **more: Any) -> ToolCall:
    return ToolCall(id, "run_code", {"language": language, "script": script, **more})


def wire(w: World, sandbox: Sandbox, fail: set[str] | None = None) -> None:
    services.register(Sandbox, sandbox)
    services.register(Runs, Wrapped(w.runs, fail) if fail else w.runs)


def test_with_the_null_sandbox_the_tool_is_not_offered(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            assert Sandbox.null().languages() == ()
            services.register(Runs, w.runs)
            assert (await tools(w).catalogue()).specs == ()

    run(scenario())


def test_with_a_sandbox_that_runs_python_one_change_tool_is_offered(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            wire(w, Recording())
            specs = (await tools(w).catalogue()).specs
            assert [spec.name for spec in specs] == ["run_code"] and specs[0].reads is False

    run(scenario())


def test_a_call_with_the_null_sandbox_is_an_error_and_records_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            services.register(Runs, w.runs)
            result = await tools(w).call(call())
            assert result.is_error and w.rows() == 0

    run(scenario())


def test_a_run_is_recorded_before_the_sandbox_is_asked_and_again_after(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            seen: list[int] = []
            sandbox = Recording(during=lambda job: seen.append(w.rows()))
            wire(w, sandbox)
            result = await tools(w).call(call("print('hi')", id="call-7", stdin="in"))
            assert seen == [1] and not result.is_error and result.call_id == "call-7"
            content = json.loads(result.content)
            assert isinstance(content, dict)
            assert "OUT-ZQ" in result.content and "FILE-ZQ" in result.content and "ran" in result.content
            [job] = sandbox.jobs
            assert (job.language, job.script, job.stdin) == ("python", "print('hi')", "in")
            stored = await w.runs.get(w.home, int(job.name.removeprefix("run-")))
            assert stored is not None and stored.output == GIVES
            assert (stored.call_id, stored.conversation_id, stored.turn_id) == ("call-7", w.conversation, w.turn)
            assert str(stored.id) in result.content

    run(scenario())


def test_the_job_is_named_for_its_run_and_every_run_has_its_own_name(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Recording()
            wire(w, sandbox)
            for n in range(3):
                await tools(w).call(call(id=f"c{n}"))
            names = [job.name for job in sandbox.jobs]
            assert len(set(names)) == 3 and all(name.startswith("run-") and name[4:].isdigit() for name in names)

    run(scenario())


def test_arguments_cannot_choose_the_pod_the_image_or_the_namespace(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Recording()
            wire(w, sandbox)
            result = await tools(w).call(call(name="../../x", image="evil", namespace="kube-system", runtime_class="runc"))
            jobs: list[Job] = sandbox.jobs
            assert result.is_error or (len(jobs) == 1 and jobs[0].name.startswith("run-") and jobs[0].name[4:].isdigit())

    run(scenario())


@pytest.mark.parametrize("arguments", [
    {}, {"language": "python"}, {"script": "print(1)"}, {"language": "ruby", "script": "puts 1"},
    {"language": "python", "script": 5}, {"language": "python", "script": None}, {"language": 3, "script": "x"},
    {"language": "python", "script": "x", "stdin": 5}, {"language": "python", "script": "x" * 20_001},
    {"language": "python", "script": "x", "stdin": "y" * 20_001}, {"language": ["python"], "script": "x"},
    {"language": "python", "script": ""}, {"language": "python", "script": " \n\t "},
])
def test_bad_arguments_are_an_error_result_and_nothing_runs(db_url: str, arguments: dict[str, object]) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Recording()
            wire(w, sandbox)
            result = await tools(w).call(ToolCall("c", "run_code", arguments))
            assert result.is_error and result.call_id == "c"
            assert sandbox.jobs == [] and w.rows() == 0

    run(scenario())


def test_a_script_at_the_limit_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Recording()
            wire(w, sandbox)
            result = await tools(w).call(call("x" * 20_000, stdin="y" * 20_000))
            assert not result.is_error and len(sandbox.jobs) == 1

    run(scenario())


def test_another_tool_name_is_an_error_and_runs_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Recording()
            wire(w, sandbox)
            result = await tools(w).call(ToolCall("c", "turn_on_light", {"language": "python", "script": "x"}))
            assert result.is_error and sandbox.jobs == [] and w.rows() == 0

    run(scenario())


def test_text_postgres_cannot_hold_is_an_error_and_nothing_runs(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Recording()
            wire(w, sandbox)
            result = await tools(w).call(call("a\x00b"))
            assert result.is_error and sandbox.jobs == [] and w.rows() == 0

    run(scenario())


def test_nothing_runs_unless_its_start_was_recorded(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Recording()
            wire(w, sandbox, {"start"})
            result = await tools(w).call(call())
            assert result.is_error and sandbox.jobs == []

    run(scenario())


def test_a_sandbox_that_cannot_run_it_is_an_error_result_not_a_raise(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            sandbox = Unavailable()
            wire(w, sandbox)
            result = await tools(w).call(call())
            assert result.is_error and len(sandbox.jobs) == 1 and w.rows() == 1

    run(scenario())


def test_a_run_the_sandbox_could_not_make_does_not_stay_looking_like_it_is_running(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            wire(w, Unavailable())
            await tools(w).call(call())
            stored = await w.runs.get(w.home, 1)
            assert stored is not None and stored.output is not None and stored.finished_at is not None
            assert stored.output.outcome != "ran"

    run(scenario())


def test_an_output_that_cannot_be_recorded_is_still_returned(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    from ashley import logs
    logs.setup()
    async def scenario() -> None:
        async with world(db_url) as w:
            wire(w, Recording(), {"finish"})
            result = await tools(w).call(call())
            assert not result.is_error and "OUT-ZQ" in result.content
            stored = await w.runs.get(w.home, 1)
            assert stored is None or stored.output is None

    capsys.readouterr()
    run(scenario())
    seen = capsys.readouterr()
    assert "runs.unrecorded" in seen.out + seen.err


def test_each_outcome_reaches_the_model_as_its_own_word(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            outcomes: tuple[Outcome, ...] = ("timed_out", "out_of_memory", "failed", "unknown")
            for outcome in outcomes:
                wire(w, Recording(Output(outcome, None, "o", "e")))
                result = await tools(w).call(call(id=outcome))
                assert outcome in result.content

    run(scenario())


def test_a_run_whose_output_was_lost_says_so_and_is_recorded_unknown(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            wire(w, Recording(Output("unknown", None, "", "")))
            result = await tools(w).call(call())
            assert not result.is_error and "unknown" in result.content
            stored = await w.runs.get(w.home, 1)
            assert stored is not None and stored.output is not None and stored.output.outcome == "unknown"

    run(scenario())


def test_a_run_a_household_made_is_not_readable_through_another(db_url: str) -> None:
    async def scenario() -> None:
        async with world(db_url) as w:
            wire(w, Recording())
            await tools(w).call(call())
            stranger = await other_household(w)
            assert await w.runs.get(w.home, 1) is not None and await w.runs.get(stranger, 1) is None

    run(scenario())


def test_the_log_carries_ids_and_outcomes_never_the_script_or_output(db_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    from ashley import logs
    logs.setup()

    async def scenario() -> None:
        async with world(db_url) as w:
            wire(w, Recording())
            capsys.readouterr()
            await tools(w).call(call("SCRIPT-ZQ9", stdin="STDIN-ZQ9"))

    run(scenario())
    seen = capsys.readouterr()
    assert "tools.call" in seen.out + seen.err and "ZQ" not in seen.out + seen.err


