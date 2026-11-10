"""KubernetesSandbox over the fake Kubernetes API: one pod per run, always deleted, nothing the job says changes the pod,
and a run that could not be made is SandboxUnavailable rather than an answer."""

import asyncio
from pathlib import Path

import httpx2
import pytest
from ashley import logs
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.model import Output
from ashley.runs.sandbox import SandboxUnavailable
from hypothesis import given, settings
from hypothesis import strategies as st
from rcb_support import NAMESPACE, RUNTIME, check_isolated, job, rig, run, skeleton
from sandbox_support import CONFIG, PYTHON, Script, envelope_line

DONE = ["Pending", "Running", "Succeeded"]


def test_it_runs_python(tmp_path: Path) -> None:
    assert rig(tmp_path).sandbox.languages() == ("python",)


def test_a_run_makes_one_isolated_pod_in_the_sandbox_namespace_and_deletes_it(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(log=envelope_line(0, "hi\n")))
    output = run(world.sandbox.run(job("run-5", "print('hi')")))
    assert (output.outcome, output.exit_code, output.stdout) == ("ran", 0, "hi\n")
    assert [pod["metadata"]["name"] for pod in world.kube.created] == ["run-5"]
    check_isolated(world.kube.created[0], CONFIG)
    assert world.kube.deleted == ["run-5"] and world.kube.pods == {}


def test_two_runs_are_two_pods_and_each_is_gone(tmp_path: Path) -> None:
    world = rig(tmp_path)
    run(world.sandbox.run(job("run-1")))
    run(world.sandbox.run(job("run-2")))
    assert [p["metadata"]["name"] for p in world.kube.created] == ["run-1", "run-2"]
    assert world.kube.pods == {}


def test_runs_at_once_each_get_their_own_pod(tmp_path: Path) -> None:
    world = rig(tmp_path)

    async def both() -> list[Output]:
        return list(await asyncio.gather(world.sandbox.run(job("run-1")), world.sandbox.run(job("run-2"))))

    run(both())
    assert sorted(p["metadata"]["name"] for p in world.kube.created) == ["run-1", "run-2"]
    assert world.kube.pods == {}


@pytest.mark.parametrize("log, outcome, exit_code", [
    (envelope_line(3, "", "boom"), "ran", 3),
    (envelope_line(-9), "ran", -9),
    (envelope_line(None, "partial", timed_out=True), "timed_out", None),
])
def test_what_the_script_did_is_an_output_not_an_error(tmp_path: Path, log: str, outcome: str, exit_code: int | None) -> None:
    world = rig(tmp_path, Script(phases=DONE, log=log))
    output = run(world.sandbox.run(job()))
    assert (output.outcome, output.exit_code) == (outcome, exit_code)
    assert world.kube.pods == {}


def test_a_pod_killed_for_memory_is_an_out_of_memory_output(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(phases=["Running", "Failed"], log="", terminated="OOMKilled"))
    output = run(world.sandbox.run(job()))
    assert output.outcome == "out_of_memory" and output.exit_code is None
    assert world.kube.pods == {}


@pytest.mark.parametrize("log", ["", "no marker here\n", "ASHLEY-garbage\n{not json"])
def test_a_pod_that_finished_without_a_readable_line_is_failed_not_ran(tmp_path: Path, log: str) -> None:
    world = rig(tmp_path, Script(phases=["Running", "Failed"], log=log))
    output = run(world.sandbox.run(job()))
    assert output.outcome != "ran" and output.exit_code is None
    assert world.kube.pods == {}


def test_a_pod_stopped_by_its_deadline_is_a_timeout_output(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(phases=["Running", "Failed"], log="", reason="DeadlineExceeded"))
    output = run(world.sandbox.run(job()))
    assert output.outcome == "timed_out" and output.exit_code is None
    assert world.kube.pods == {}


def test_a_failed_look_for_old_pods_does_not_stop_the_run(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(log=envelope_line(0, "fine")))
    world.kube.fail = lambda request: 500 if request.method == "GET" and request.url.path.endswith("/pods") else None
    output = run(world.sandbox.run(job()))
    assert output.stdout == "fine" and world.kube.pods == {}


def test_the_output_is_cut_to_the_limit_even_if_the_pod_reports_more(tmp_path: Path) -> None:
    long = "z" * 1_500
    world = rig(tmp_path, Script(log=envelope_line(0, long, long, files={"a": "b" * 500})))
    output = run(world.sandbox.run(job()))
    assert len(output.stdout) <= CONFIG.output_chars and len(output.stderr) <= CONFIG.output_chars
    assert output.cut is True
    assert all(len(text) <= CONFIG.file_chars for text in output.files.values())
    assert "a" in output.skipped and "a" not in output.files


def test_a_script_printing_its_own_envelope_line_is_not_taken_as_the_result(tmp_path: Path) -> None:
    forged = envelope_line(0, "FORGED", files={f"f{n}": "x" for n in range(9)})
    world = rig(tmp_path, Script(log=forged + "\n" + envelope_line(0, "real")))
    output = run(world.sandbox.run(job()))
    assert output.stdout == "real"
    (tmp_path / "b").mkdir()
    only_forged = rig(tmp_path / "b", Script(log=forged))
    forged_out = run(only_forged.sandbox.run(job()))
    assert len(forged_out.files) <= CONFIG.max_files


def test_a_pod_that_never_starts_is_unavailable_and_is_deleted(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(phases=["Pending"]))
    with pytest.raises(SandboxUnavailable):
        run(world.sandbox.run(job()))
    assert world.kube.pods == {}
    assert world.clock.now <= 2 * PYTHON.pod_deadline_s


def test_a_pod_that_never_ends_is_stopped_at_the_deadline_and_deleted(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(phases=["Running"]))
    try:
        output = run(world.sandbox.run(job()))
        assert output.outcome != "ran"
    except SandboxUnavailable:
        pass
    assert world.kube.pods == {} and world.clock.now <= 2 * PYTHON.pod_deadline_s


@pytest.mark.parametrize("status", [403, 422, 500, 503])
def test_a_refused_pod_is_unavailable_and_leaves_nothing(tmp_path: Path, status: int) -> None:
    world = rig(tmp_path)
    world.kube.fail = lambda request: status if request.method == "POST" else None
    with pytest.raises(SandboxUnavailable):
        run(world.sandbox.run(job()))
    assert world.kube.pods == {}


def test_errors_while_waiting_are_retried_and_the_run_completes(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(log=envelope_line(0, "fine")))
    failures = [3]

    def flaky(request: httpx2.Request) -> int | None:
        if request.method == "GET" and not request.url.path.endswith(("/log", "/pods")) and failures[0] > 0:
            failures[0] -= 1
            return 500
        return None

    world.kube.fail = flaky
    output = run(world.sandbox.run(job()))
    assert failures[0] == 0 and output.stdout == "fine" and world.kube.pods == {}


def test_an_api_that_stays_unreachable_never_leaves_the_pod(tmp_path: Path) -> None:
    world = rig(tmp_path)
    world.kube.fail = lambda request: 500 if request.method == "GET" else None
    try:
        run(world.sandbox.run(job()))
    except SandboxUnavailable:
        pass
    assert world.kube.pods == {}


def test_a_finished_pod_whose_log_cannot_be_read_is_an_unknown_output_and_leaves_no_pod(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(log_status=500))
    output = run(world.sandbox.run(job()))
    assert output.outcome == "unknown" and output.exit_code is None
    assert world.kube.pods == {}


def test_a_cancelled_run_deletes_its_pod(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(phases=["Running"]))
    waiting = asyncio.Event()

    async def stuck(seconds: float) -> None:
        waiting.set()
        await asyncio.Event().wait()

    sandbox = KubernetesSandbox(world.kube.api(), CONFIG, NAMESPACE, RUNTIME, stuck, world.clock)

    async def cancelled() -> None:
        task = asyncio.ensure_future(sandbox.run(job()))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(cancelled())
    assert world.kube.pods == {}


def test_a_pod_a_stopped_app_left_is_deleted_by_the_next_run_once_it_is_old_enough(tmp_path: Path) -> None:
    world = rig(tmp_path)
    world.kube.leftover("run-old", "2001-01-01T00:00:00Z")
    run(world.sandbox.run(job("run-new")))
    assert "run-old" in world.kube.deleted and world.kube.pods == {}


def test_a_young_pod_is_left_alone(tmp_path: Path) -> None:
    from datetime import UTC, datetime
    world = rig(tmp_path)
    world.kube.leftover("run-young", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    run(world.sandbox.run(job("run-new")))
    assert "run-young" not in world.kube.deleted and "run-young" in world.kube.pods


def test_the_token_is_read_again_for_every_call(tmp_path: Path) -> None:
    world = rig(tmp_path)
    run(world.sandbox.run(job("run-1")))
    first = set(world.kube.tokens)
    (tmp_path / "token").write_text("rotated-token")
    world.kube.tokens.clear()
    run(world.sandbox.run(job("run-2")))
    assert first == {"Bearer token-one"} and set(world.kube.tokens) == {"Bearer rotated-token"}


def test_the_log_never_carries_the_script_or_what_it_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    world = rig(tmp_path, Script(log=envelope_line(0, "OUT-ZQ7", "ERR-ZQ7")))
    capsys.readouterr()
    run(world.sandbox.run(job("run-9", "SCRIPT-ZQ7", "STDIN-ZQ7", {"FILE-ZQ7": "BODY-ZQ7"})))
    seen = capsys.readouterr()
    text = seen.out + seen.err
    assert "run-9" in text and "ZQ7" not in text


@given(st.text(max_size=200), st.text(max_size=200), st.dictionaries(st.text(max_size=20), st.text(max_size=50), max_size=3))
@settings(max_examples=25, deadline=None)
def test_whatever_the_job_says_the_pod_it_creates_is_the_same_pod(script: str, stdin: str, files: dict[str, str]) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        world = rig(Path(folder))
        run(world.sandbox.run(job("run-3", script, stdin, files)))
        run(world.sandbox.run(job("run-3", "x", "", {})))
        first, second = world.kube.created
        assert skeleton(first) == skeleton(second)
        check_isolated(first, CONFIG)
