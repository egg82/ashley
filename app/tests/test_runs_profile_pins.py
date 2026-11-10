"""What a run's pod is told and how long the sandbox keeps asking about it, pinned value by value against the config
the pod is made from: the limits the runner gets, the bytes of log read, the pause between reads, and how old a
leftover pod must be before it is swept."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from ashley.runs.kubernetes import KubernetesSandbox
from ashley.runs.model import Job
from ashley.runs.pod_spec import manifest
from sandbox_support import CONFIG, PYTHON, Clock, FakeKube, Script

JOB = Job("run-7", "python", "print(1)")


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token")


def test_the_runner_is_told_the_configured_limits() -> None:
    env = {e["name"]: e["value"] for e in manifest(JOB, CONFIG, "", "gvisor")["spec"]["containers"][0]["env"]}
    assert json.loads(env["ASHLEY_LIMITS"]) == {
        "timeout_s": PYTHON.script_timeout_s, "output_chars": CONFIG.output_chars, "file_chars": CONFIG.file_chars,
        "max_files": CONFIG.max_files, "log_bytes": PYTHON.log_bytes}


def test_the_log_is_read_up_to_the_configured_bytes_and_polled_at_the_configured_pause(fake: FakeKube) -> None:
    asked: list[str] = []

    def record(request: httpx2.Request) -> None:
        if request.url.path.endswith("/log"):
            asked.append(request.url.params["limitBytes"])

    fake.fail = record
    clock = Clock()
    asyncio.run(KubernetesSandbox(fake.api(), CONFIG, "ashley-sandbox", "gvisor", sleep=clock.sleep, clock=clock).run(JOB))
    assert asked == [str(PYTHON.log_bytes)]
    assert clock.now == 2 * CONFIG.poll_s


def test_a_leftover_pod_is_swept_only_past_twice_the_pod_deadline(fake: FakeKube) -> None:
    now = datetime.now(UTC)

    def age(seconds: float) -> str:
        return (now - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

    fake.leftover("run-1", age(1.5 * PYTHON.pod_deadline_s))
    fake.leftover("run-2", age(2.5 * PYTHON.pod_deadline_s))
    fake.script = Script()
    clock = Clock()
    asyncio.run(KubernetesSandbox(fake.api(), CONFIG, "ashley-sandbox", "gvisor", sleep=clock.sleep, clock=clock).run(JOB))
    assert "run-2" in fake.deleted and "run-1" not in fake.deleted
