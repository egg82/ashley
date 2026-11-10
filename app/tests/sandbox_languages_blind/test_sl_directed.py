"""Directed tests for the planted mutants the contract tests let live (see MUTANTS.txt)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ashley.runs.config import LINE_OVERHEAD, WORST_BYTES_PER_CHAR, parse
from ashley.runs.pod_spec import manifest
from sandbox_languages_support import config, container, job, rig, run, shipped_data
from sandbox_support import Script, envelope_line


def test_a_language_with_no_name_in_the_contract_is_refused_under_languages() -> None:
    data = shipped_data()
    data["languages"]["cobol"] = dict(data["languages"]["build123d"])
    with pytest.raises(ValueError):
        parse(data)


def test_python_s_log_must_have_room_for_both_streams() -> None:
    data = shipped_data()
    data["languages"]["python"]["log_bytes"] = 100
    with pytest.raises(ValueError):
        parse(data)


def room(output_chars: int) -> int:
    return 2 * output_chars * WORST_BYTES_PER_CHAR + LINE_OVERHEAD


@pytest.mark.parametrize("where", ["python", "build123d"])
def test_a_log_with_exactly_room_for_both_streams_parses_and_one_byte_less_does_not(where: str) -> None:
    def data(log_bytes: int) -> dict[str, Any]:
        made = shipped_data()
        target = made["languages"][where]
        target["log_bytes"] = log_bytes
        return made

    needed = room(shipped_data()["output_chars"])
    assert parse(data(needed)) is not None
    with pytest.raises(ValueError):
        parse(data(needed - 1))


def limits(made: dict[str, Any]) -> dict[str, Any]:
    entry = next(e for e in container(made)["env"] if e["name"] == "ASHLEY_LIMITS")
    found: dict[str, Any] = json.loads(entry["value"])
    return found


def test_each_pod_carries_its_languages_script_timeout_and_log_limit() -> None:
    cfg = config()
    python, cad = limits(manifest(job("python"), cfg, "r", "gvisor")), limits(manifest(job("build123d"), cfg, "r", "gvisor"))
    assert (python["timeout_s"], python["log_bytes"]) == (10, cfg.languages["python"].log_bytes)
    assert (cad["timeout_s"], cad["log_bytes"]) == (60, 300_000)


def test_a_pod_between_one_and_two_longest_deadlines_old_is_kept(tmp_path: Path) -> None:
    world = rig(tmp_path)
    made = (datetime.now(UTC) - timedelta(seconds=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
    world.kube.leftover("run-cad", made)
    run(world.sandbox.run(job("python", "run-2")))
    assert "run-cad" in world.kube.pods


def test_a_build123d_run_sweeps_leftovers_like_any_other(tmp_path: Path) -> None:
    world = rig(tmp_path, Script(log=envelope_line(0)))
    world.kube.leftover("run-old", (datetime.now(UTC) - timedelta(seconds=300)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    run(world.sandbox.run(job("build123d", "run-2")))
    assert "run-old" in world.kube.deleted
