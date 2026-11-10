"""What the pod's runner puts in its one line: binary files only under a profile with a budget, in name order while their
sizes fit, the rest named in `skipped`, the whole line inside the log limit, links never followed."""

import json
import os
from pathlib import Path
from typing import Any

from ashley.runs import config, envelope, runner
from run_artifacts_lines import CAD_LIMITS, PY_LIMITS, noise, pod_line
from run_artifacts_support import ASCII_STL, GOOD, glb, stl

CFG = config.load()


def body_of(line: str) -> dict[str, Any]:
    assert line.startswith(runner.MARK)
    out: dict[str, Any] = json.loads(line[len(runner.MARK):])
    return out


def test_a_python_profile_line_has_no_artifacts_key_and_leaves_a_binary_file_alone(tmp_path: Path) -> None:
    body = body_of(pod_line(tmp_path, {"out/m.glb": glb(b"x")}, limits=PY_LIMITS))
    assert "artifacts" not in body


def test_an_ascii_stl_is_a_text_file_for_python_and_an_artifact_by_suffix_for_cad(tmp_path: Path) -> None:
    text = {"cube.stl": ASCII_STL.decode()}
    py = body_of(pod_line(tmp_path / "py", {}, text, PY_LIMITS))
    assert "cube.stl" in py["files"] and "artifacts" not in py
    cad = body_of(pod_line(tmp_path / "cad", {}, text))
    assert "cube.stl" in cad["artifacts"] and "cube.stl" not in cad["files"]


def test_a_cad_line_carries_the_three_mesh_files_and_they_read_back_whole(tmp_path: Path) -> None:
    line = pod_line(tmp_path, GOOD)
    body = body_of(line)
    assert set(body["artifacts"]) == set(GOOD)
    out = envelope.parse(line, CFG, CAD_LIMITS["artifact_bytes"])
    assert out is not None and dict(out.artifacts) == GOOD


def test_files_that_are_not_meshes_are_not_carried(tmp_path: Path) -> None:
    body = body_of(pod_line(tmp_path, {"data.bin": b"\x00\x01", "readme.glb.txt": b"x", "a.glb": glb()}))
    assert set(body["artifacts"]) == {"a.glb"}


def test_files_are_carried_in_name_order_while_their_sizes_fit_and_the_rest_are_named(tmp_path: Path) -> None:
    a, b = noise(60, "a"), noise(60, "b")
    limits = CAD_LIMITS | {"artifact_bytes": 100}
    body = body_of(pod_line(tmp_path, {"b.glb": b, "a.glb": a}, limits=limits))
    assert set(body["artifacts"]) == {"a.glb"}
    assert "b.glb" in body["skipped"]


def test_sizes_that_add_up_to_exactly_the_budget_are_all_carried(tmp_path: Path) -> None:
    limits = CAD_LIMITS | {"artifact_bytes": 100}
    body = body_of(pod_line(tmp_path, {"a.glb": noise(50, "a"), "b.stl": noise(50, "b")}, limits=limits))
    assert set(body["artifacts"]) == {"a.glb", "b.stl"}


def test_a_line_that_would_pass_the_log_limit_leaves_the_file_out_and_names_it(tmp_path: Path) -> None:
    limits = CAD_LIMITS | {"log_bytes": 262144}
    line = pod_line(tmp_path, {"big.glb": noise(300_000), "small.stl": stl(1)}, limits=limits)
    assert len(line.encode()) <= limits["log_bytes"]
    body = body_of(line)
    assert "big.glb" not in body.get("artifacts", {}) and "big.glb" in body["skipped"]


def test_a_link_is_not_followed(tmp_path: Path) -> None:
    secret = tmp_path / "outside.glb"
    secret.write_bytes(glb(b"secret"))
    work = tmp_path / "work"
    work.mkdir()
    os.symlink(secret, work / "link.glb")
    body = body_of(pod_line(tmp_path, {}, limits=CAD_LIMITS))
    assert "link.glb" not in body.get("artifacts", {})


def test_a_line_exactly_as_long_as_the_log_allows_carries_the_file_and_one_byte_less_does_not(tmp_path: Path) -> None:
    data = {"a.glb": noise(3000)}
    whole = pod_line(tmp_path / "w", data)
    size = len(whole.encode()) + 1
    exact = pod_line(tmp_path / "e", data, limits=CAD_LIMITS | {"log_bytes": size})
    assert "a.glb" in body_of(exact)["artifacts"] and len(exact.encode()) + 1 <= size
    short = pod_line(tmp_path / "s", data, limits=CAD_LIMITS | {"log_bytes": size - 1})
    assert "a.glb" not in body_of(short)["artifacts"] and "a.glb" in body_of(short)["skipped"]
    assert len(short.encode()) + 1 <= size - 1
