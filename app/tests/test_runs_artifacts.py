"""Binary artifacts through the runner and the envelope: a profile with an `artifact_bytes` budget carries the files named
by `runner.ARTIFACT_SUFFIXES` back, deflated, within the budget and the log; a profile without one reads and writes
exactly what it did."""

import base64
import json
import random
import zlib
from pathlib import Path
from typing import Any

import pytest
from ashley.runs import config, envelope, runner
from ashley.runs.model import Output
from ashley.runs.pod_spec import manifest
from ashley.runs.model import Job
from sandbox_support import CONFIG

LIMITS = {"timeout_s": 10, "output_chars": 50, "file_chars": 40, "max_files": 2, "log_bytes": 1 << 20}
WITH = {**LIMITS, "artifact_bytes": 100}


def made(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, Path]:
    out, work = tmp_path / "out", tmp_path / "work"
    out.mkdir()
    work.mkdir()
    (out / "stdout").write_text("")
    (out / "stderr").write_text("")
    for name, data in files.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_bytes(data)
    return out, work


def body(line: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(line[len(runner.MARK):])
    return loaded


def artifacts_of(got: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = got["artifacts"]
    return found


def test_without_a_budget_the_line_has_no_artifacts_key_and_a_binary_file_is_skipped(tmp_path: Path) -> None:
    out, work = made(tmp_path, {"out/m.glb": b"glTF\x00\xff", "a.txt": "x".encode()})
    got = body(runner.line(0, False, out, work, LIMITS))
    assert "artifacts" not in got and got["files"] == {"a.txt": "x"} and got["skipped"] == ["out/m.glb"]


def test_a_text_file_with_an_artifact_suffix_stays_text_without_a_budget(tmp_path: Path) -> None:
    out, work = made(tmp_path, {"m.stl": b"solid x"})
    assert body(runner.line(0, False, out, work, LIMITS))["files"] == {"m.stl": "solid x"}


def test_with_a_budget_artifacts_come_back_deflated_and_are_neither_files_nor_skipped(tmp_path: Path) -> None:
    out, work = made(tmp_path, {"out/m.glb": b"glTF" * 10, "out/m.STL": b"nope", "out/m.3mf": b"PK\x03\x04", "out/r.txt": b"t"})
    got = body(runner.line(0, False, out, work, WITH))
    assert got["files"] == {"out/m.STL": "nope", "out/r.txt": "t"} and got["skipped"] == []
    assert set(artifacts_of(got)) == {"out/m.glb", "out/m.3mf"}


def test_artifacts_past_the_budget_are_named_skipped_and_never_split(tmp_path: Path) -> None:
    out, work = made(tmp_path, {"a.glb": b"x" * 60, "b.stl": b"y" * 60, "c.3mf": b"z" * 30})
    got = body(runner.line(0, False, out, work, WITH))
    assert sorted(artifacts_of(got)) == ["a.glb", "c.3mf"] and got["skipped"] == ["b.stl"]


def test_artifacts_that_fill_the_budget_exactly_are_all_kept(tmp_path: Path) -> None:
    out, work = made(tmp_path, {"a.glb": b"x" * 50, "b.stl": b"y" * 50, "c.3mf": b"z"})
    got = body(runner.line(0, False, out, work, WITH))
    assert sorted(artifacts_of(got)) == ["a.glb", "b.stl"] and got["skipped"] == ["c.3mf"]


def test_an_artifact_that_would_overrun_the_log_is_named_skipped(tmp_path: Path) -> None:
    incompressible = random.Random(1).randbytes(2048)
    out, work = made(tmp_path, {"a.glb": incompressible})
    line = runner.line(0, False, out, work, {**WITH, "artifact_bytes": 1 << 20, "log_bytes": 1500})
    assert len((line + "\n").encode()) <= 1500
    assert artifacts_of(body(line)) == {} and body(line)["skipped"] == ["a.glb"]


def read(tmp_path: Path, files: dict[str, bytes], limits: dict[str, int]) -> Output | None:
    out, work = made(tmp_path, files)
    return envelope.parse(runner.line(0, False, out, work, limits), CONFIG, limits.get("artifact_bytes", 0))


def test_the_line_reads_back_as_the_artifacts_it_carried(tmp_path: Path) -> None:
    data = {"out/m.glb": b"glTF\x02\x00\x00\x00" * 5, "out/m.3mf": bytes(range(200))}
    found = read(tmp_path, data, {**WITH, "artifact_bytes": 1000})
    assert found is not None and dict(found.artifacts) == data and found.skipped == ()


def test_a_profile_without_a_budget_ignores_artifacts_in_a_line() -> None:
    line = runner.MARK + json.dumps({"exit_code": 0, "timed_out": False, "stdout": "", "stderr": "", "cut": False,
                                     "files": {}, "skipped": [], "artifacts": {"a.glb": _packed(b"abc")}})
    assert envelope.parse(line, CONFIG) == Output("ran", 0, "", "", False, {}, ())


def _packed(data: bytes) -> str:
    return base64.b64encode(zlib.compress(data)).decode()


def forged(artifacts: object) -> Output:
    line = runner.MARK + json.dumps({"exit_code": 0, "timed_out": False, "stdout": "", "stderr": "", "cut": False,
                                     "files": {}, "skipped": [], "artifacts": artifacts})
    found = envelope.parse(line, CONFIG, 50)
    assert found is not None
    return found


@pytest.mark.parametrize("name", ["../m.glb", "/m.glb", "m.png", "m.glb/", ""])
def test_a_forged_artifact_with_a_bad_name_is_skipped(name: str) -> None:
    got = forged({name: _packed(b"abc")})
    assert got.artifacts == {} and got.skipped == (name,)


@pytest.mark.parametrize("text", ["!!!", _packed(b"abc")[:-4], base64.b64encode(b"not zlib").decode(), "", 5, None,
                                  _packed(b"")])
def test_a_forged_artifact_that_is_not_deflated_bytes_is_skipped(text: object) -> None:
    assert forged({"m.glb": text}).artifacts == {}


def test_a_forged_artifact_is_cut_at_the_budget_however_small_it_deflates() -> None:
    bomb = _packed(b"\x00" * 10_000_000)
    assert len(bomb) < 20_000
    got = forged({"a.glb": bomb, "b.glb": _packed(b"x" * 50)})
    assert dict(got.artifacts) == {"b.glb": b"x" * 50}
    assert "a.glb" in got.skipped


def test_the_budget_is_shared_by_the_artifacts_and_their_count_is_max_files() -> None:
    got = forged({"a.glb": _packed(b"x" * 30), "b.glb": _packed(b"x" * 30), "c.glb": _packed(b"x")})
    assert set(got.artifacts) == {"a.glb", "c.glb"} and got.skipped == ("b.glb",)
    many = forged({f"{i}.glb": _packed(b"x") for i in range(3)})
    assert len(many.artifacts) == CONFIG.max_files and len(many.skipped) == 1


def test_a_binary_profile_pod_is_given_the_budget_and_the_python_pod_is_not() -> None:
    shipped = config.load().with_image("build123d", "r.test/cad@sha256:" + "c" * 64)
    env = {e["name"]: e["value"] for e in manifest(Job("run-1", "build123d", "x"), shipped, "r", "gvisor")["spec"]["containers"][0]["env"]}
    assert json.loads(env["ASHLEY_LIMITS"])["artifact_bytes"] == shipped.languages["build123d"].artifact_bytes
    py = {e["name"]: e["value"] for e in manifest(Job("run-1", "python", "x"), shipped, "r", "gvisor")["spec"]["containers"][0]["env"]}
    assert "artifact_bytes" not in json.loads(py["ASHLEY_LIMITS"])


def test_artifacts_may_not_exceed_the_working_directory() -> None:
    shipped = json.loads(config.FILE.read_text())
    shipped["languages"]["build123d"]["artifact_bytes"] = 33 * 1024 * 1024
    with pytest.raises(ValueError):
        config.parse(shipped)
    shipped["languages"]["build123d"]["artifact_bytes"] = 0
    with pytest.raises(ValueError):
        config.parse(shipped)
