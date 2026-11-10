"""Binary inputs reach the runner whole: deflated and cut into chunks small enough for one environment string each,
written read-only under `inputs/` in the working directory, and never carried back as the run's own output."""

import os
import random
from pathlib import Path

from hypothesis import given, settings, strategies as st

from ashley.runs import runner
from ashley.runs.model import Job
from ashley.runs.pod_spec import BLOB_CHUNK, manifest
from sandbox_support import CONFIG

MODELS = Path(__file__).parent / "cad_models"
LINUX_STRING_MAX = 128 * 1024
NAMES = st.text(st.characters(blacklist_characters="\x00/", blacklist_categories=("Cs",)), min_size=1, max_size=20)


def env_of(job: Job) -> dict[str, str]:
    env = manifest(job, CONFIG, "", "gvisor")["spec"]["containers"][0]["env"]
    return {e["name"]: e["value"] for e in env}


@settings(max_examples=40, deadline=None)
@given(st.dictionaries(NAMES, st.binary(max_size=3000), max_size=3))
def test_any_bytes_reach_the_runner_unchanged(inputs: dict[str, bytes]) -> None:
    assert runner.blobs(env_of(Job("run-1", "python", "", inputs=inputs))) == inputs


def test_a_real_model_and_data_that_does_not_compress_cross_several_chunks_and_every_string_fits_linux() -> None:
    real = (MODELS / "featuretype.STL").read_bytes()
    noise = random.Random(7).randbytes(300_000)
    env = env_of(Job("run-1", "python", "", inputs={"7.stl": real, "8.3mf": noise}))
    assert sum(k.startswith("ASHLEY_BLOB_001_") for k in env) > 3
    assert max(len(v) for v in env.values()) <= BLOB_CHUNK < LINUX_STRING_MAX
    assert runner.blobs(env) == {"7.stl": real, "8.3mf": noise}


def test_a_job_with_no_inputs_adds_no_variables() -> None:
    assert not any(k.startswith("ASHLEY_BLOB") for k in env_of(Job("run-1", "python", "x")))


def test_inputs_are_written_read_only_under_inputs_and_an_unsafe_name_is_skipped(tmp_path: Path) -> None:
    runner.place_blobs(tmp_path, {"7.stl": b"abc", "../x.stl": b"no", "/etc/y": b"no"})
    assert [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()] == ["inputs/7.stl"]
    assert (tmp_path / "inputs" / "7.stl").read_bytes() == b"abc"
    assert not os.access(tmp_path / "inputs" / "7.stl", os.W_OK) or os.getuid() == 0


def test_inputs_are_not_the_runs_output_whatever_their_type(tmp_path: Path) -> None:
    runner.place_blobs(tmp_path, {"7.stl": b"binary\xff", "8.step": b"ISO-10303-21;"})
    (tmp_path / "made.txt").write_text("mine")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "model.stl").write_bytes(b"made")
    files, skipped = runner.left(tmp_path, file_chars=100, max_files=5, apart=runner.ARTIFACT_SUFFIXES)
    assert (files, skipped) == ({"made.txt": "mine"}, [])
    assert sorted(runner.artifacts(tmp_path, budget=10_000)[0]) == ["out/model.stl"]
    assert sorted(runner.artifacts(tmp_path, budget=10_000)[1]) == []
