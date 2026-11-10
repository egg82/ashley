"""The bench replay end to end with the scripted policy over a synthetic snapshot, on a migrated database and her real
turn loop, Workshop and Runs, with a sandbox that answers every run with one fixed report: each ask is answered, the
person's photo lands between asks and the household turn it starts is answered, and the records the replay leaves are
measured; the records mode measures the captured conversation the same way, its run executed again."""

import asyncio
import dataclasses
import hashlib
import json
from collections.abc import Generator
from typing import Any, TypeVar

from pydantic import BaseModel

import pytest
from ashley import services, wiring
from ashley.channels import inflight_config, resume
from ashley.db.database import Database
from ashley.db.migrate import migrate
from ashley.evals import bench_replay
from ashley.evals.bench_act_policy import Scripted, reply
from ashley.evals.bench_replay import Options
from ashley.evals.bench_replay_grader import ScriptedGrader
from ashley.evals.bench_replay_snapshot import Command, Said, Snapshot, load, write
from ashley.inference.inference import Inference, InferenceUnavailable
from ashley.inference.model import Prompt, Task, ToolCalls
from ashley.runs.model import Job, Language, Output
from ashley.runs.sandbox import Sandbox, SandboxUnavailable
from ashley.settings import Settings

T = TypeVar("T", bound=BaseModel)
T0 = 1_800_000_000.0
PHOTO = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SHA = hashlib.sha256(PHOTO).hexdigest()
REPORT: dict[str, Any] = {"unit": "mm", "triangles": 12, "overlap_parts_skipped": 0,
          "parts": [{"name": n, "volume": 1.0, "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}} for n in ("a", "b")],
          "checks": [{"name": "w", "actual": 1.0, "op": "==", "target": 2.0, "tolerance": 0.1, "rests_on": []}],
          "overlaps": [{"a": "a", "b": "b", "volume_mm3": 0.5, "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]}}]}


class Fixed(Sandbox):
    def languages(self) -> tuple[Language, ...]:
        return ("build123d",)

    async def run(self, job: Job) -> Output:
        return Output("ran", 0, "", "", files={"out/report.json": json.dumps(REPORT)})


def added(seq: int, at: float, kind: str, title: str, body: str, person: bool = False) -> Command:
    command = {"type": "add", "kind": kind, "title": title, "body": body, "size": "medium"}
    piece = {"id": seq, "kind": kind, "title": title, "body": body, "version": 1}
    return Command(seq, at, person, False, command, "accepted", {"type": "added", "piece": piece})


def ran(seq: int, at: float, version: int, person: bool = False) -> Command:
    return Command(seq, at, person, False, {"type": "run", "language": "build123d", "piece_id": 2,
                                           "base_version": version}, "accepted", {"type": "ran"})


def snapshot() -> Snapshot:
    rows = json.dumps({"items": [{"name": "w", "value": 2, "unit": "mm", "source": "guessed"}]})
    photo = json.dumps({"sha256": SHA, "size": len(PHOTO), "media_type": "image/png", "name": "p.png"})
    commands = (added(1, T0 - 900, "measurements", "Sizes", rows), added(2, T0 - 800, "model", "Model", "show()"),
                ran(3, T0 - 700, 1), ran(4, T0 + 20, 1), added(5, T0 + 50, "image", "p.png", photo, person=True),
                ran(6, T0 + 150, 1, person=True))
    turns = (Said(1, 1, "person", T0 - 1000, False, None, "start"), Said(2, 1, "ashley", T0 - 990, False, 1, "Started."),
             Said(5, 2, "person", T0, False, None, "make it"), Said(6, 2, "ashley", T0 + 30, False, 5, "Made."),
             Said(7, 2, "household", T0 + 100, False, None, "1 changes", "bench_react:9:5"),
             Said(8, 2, "ashley", T0 + 110, False, 7, "Seen."), Said(9, 2, "person", T0 + 200, False, None, "again"),
             Said(10, 2, "ashley", T0 + 260, False, 9, "Again."))
    return Snapshot("UTC", "Ann", "Clip", "3d", 2, 5, commands, turns, ())


@pytest.fixture
def wired(empty_database: str) -> Generator[str]:
    migrate(empty_database)
    closers = wiring.wire(Settings(database_url=empty_database, build_version="test"))
    services.register(Sandbox, Fixed())
    services.register(Inference, Scripted("replay", piece=2))
    yield empty_database
    for close in closers:
        asyncio.run(close())


def replayed(url: str, options: Options) -> bench_replay.Result:
    """The replay in one event loop, the database's pool opened and closed in it."""
    async def scenario() -> bench_replay.Result:
        await services.get(Database).open()
        try:
            return await bench_replay.replay(snapshot(), {SHA: PHOTO}, url, ScriptedGrader(), options)
        finally:
            await services.get(Database).close()
    return asyncio.run(scenario())


def test_a_snapshot_reads_back_as_written(tmp_path: object) -> None:
    from pathlib import Path
    where = Path(str(tmp_path))
    write(where, snapshot(), {SHA: PHOTO})
    got, files = load(where)
    assert got == snapshot() and files == {SHA: PHOTO}
    assert [t.id for t in got.asks()] == [5, 7, 9] and [t.id for t in got.before()] == [1, 2]


def test_every_ask_is_answered_and_measured_from_what_the_replay_left(wired: str) -> None:
    result = replayed(wired, Options(poll_s=0.05, answer_timeout_s=20))
    assert result.failed == {} and result.diverged == {}
    by = {a.author: a for a in result.asks}
    assert [a.author for a in result.asks] == ["person", "household", "person"]
    first = result.asks[0]
    assert first.model_runs == 1 and first.build_s is not None and first.build_s >= 0
    assert (first.overlaps_final, first.failed_checks_final) == (1, 1)
    assert first.claimed_unbacked is True and first.unasked_changes == 0
    assert by["household"].model_runs == 1 and result.asks[2].measurement_reasks == 1
    assert len(result.runs) == 5 and result.cost_usd is None
    assert sorted(result.captured.values()) == [5, 7, 9] and set(result.captured) == {a.turn_id for a in result.asks}


def test_the_records_mode_measures_the_captured_conversation(wired: str) -> None:
    result = replayed(wired, Options(records=True))
    assert result.mode == "records" and result.diverged == {}
    first = result.asks[0]
    assert (first.build_s, first.model_runs, first.overlaps_final) == (20.0, 1, 1)
    assert [r["seq"] for r in result.runs] == [4, 6]


class Down(Sandbox):
    def languages(self) -> tuple[Language, ...]:
        return ("build123d",)

    async def run(self, job: Job) -> Output:
        raise SandboxUnavailable("down")


def test_a_logged_run_the_sandbox_cannot_run_again_is_reported_as_diverged(wired: str) -> None:
    services.register(Sandbox, Down())
    result = replayed(wired, Options(records=True))
    assert result.diverged == {4: "accepted->unavailable", 6: "accepted->unavailable"} and result.asks[0].build_s is None


class HoldsThenFails(Scripted):
    """Says first that it is not the answer yet, so the turn holds and goes on in the background, then fails its third
    step once, as a provider timing out does."""

    async def step(self, task: Task, prompt: Prompt, output: type[T], *,
                   conversation_id: int | None = None) -> T | ToolCalls:
        self.calls = getattr(self, "calls", 0) + 1
        if self.calls == 1:
            return output.model_validate(reply(answers=False).model_dump())
        if self.calls == 3:
            raise InferenceUnavailable("scripted timeout")
        return await super().step(task, prompt, output, conversation_id=conversation_id)


def test_a_turn_kept_when_its_model_call_failed_is_finished_by_the_inflight_sweep(
        wired: str, monkeypatch: pytest.MonkeyPatch) -> None:
    quick = dataclasses.replace(inflight_config.CONFIG, unavailable_retry_s=1, poll_s=0.2)
    monkeypatch.setattr(inflight_config, "CONFIG", quick)
    monkeypatch.setattr(resume, "CONFIG", quick)
    services.register(Inference, HoldsThenFails("replay", piece=2))
    result = replayed(wired, Options(poll_s=0.2, answer_timeout_s=30))
    assert result.failed == {} and len(result.asks) == 3 and result.asks[0].model_runs == 1
