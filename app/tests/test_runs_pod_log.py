"""`PodLog` against a fake API (`sandbox_support.FakeKube`): the log is asked for with exactly the byte limit it was
given, and the sweep deletes a leftover pod only once it is past twice the deadline."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from ashley.runs.pod_log import PodLog
from sandbox_support import Clock, FakeKube, Script

LABEL = "ashley.yggdrasil.pub/run"
DEADLINE_S = 100
LOG_BYTES = 4096


def run(fake: FakeKube) -> str:
    clock = Clock()
    pods = PodLog(fake.api(), "ashley-sandbox", LABEL, LOG_BYTES, 0.5, logging.getLogger("ashley.runs"), "test",
                  sleep=clock.sleep, clock=clock)
    manifest = {"metadata": {"name": "job-a1", "labels": {LABEL: "true"}}}
    return asyncio.run(pods.run(manifest, DEADLINE_S))


def ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def fake(tmp_path: Path) -> FakeKube:
    return FakeKube(tmp_path / "token", Script(log="done"))


def test_the_log_is_asked_for_with_the_byte_limit_it_was_given(fake: FakeKube) -> None:
    asked: list[str] = []

    def watch(request: httpx2.Request) -> int | None:
        if request.url.path.endswith("/log"):
            asked.append(request.url.params["limitBytes"])
        return None

    fake.fail = watch
    assert run(fake) == "done"
    assert asked == [str(LOG_BYTES)]


def test_a_leftover_pod_is_swept_only_once_past_twice_the_deadline(fake: FakeKube) -> None:
    fake.leftover("job-young", ago(0))
    fake.leftover("job-past-deadline", ago(1.5 * DEADLINE_S))
    fake.leftover("job-old", ago(2.5 * DEADLINE_S))
    run(fake)
    assert sorted(fake.deleted) == ["job-a1", "job-old"]
