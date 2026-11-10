"""The real runner: what the bridge hands the `herdr` binary arrives verbatim, one argument each, through no shell."""

from pathlib import Path

import pytest
from herdr_bridge.runner import HerdrMissing, HerdrTimeout, SubprocessRunner


def binary(tmp: Path, body: str) -> str:
    path = tmp / "notherdr"
    path.write_text("#!/usr/bin/env bash\n" + body + "\n")
    path.chmod(0o755)
    return str(path)


def test_arguments_arrive_verbatim_and_nothing_is_interpreted(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    args = [
        "agent", "prompt", "w1:p1", f"--x; touch {marker}", f"$(touch {marker})", f"`touch {marker}`",
        "a b", "-", "--", "--help", "line1\nline2", "*", "~", "",
    ]
    done = SubprocessRunner(binary(tmp_path, 'printf "%s\\0" "$@"')).run(args, 5.0)
    assert done.code == 0
    assert done.out.split("\0")[:-1] == args
    assert not marker.exists()


def test_the_exit_code_and_both_streams_come_back(tmp_path: Path) -> None:
    done = SubprocessRunner(binary(tmp_path, "echo out; echo err >&2; exit 3")).run(["x"], 5.0)
    assert (done.code, done.out, done.err) == (3, "out\n", "err\n")


def test_a_binary_that_does_not_finish_is_a_timeout(tmp_path: Path) -> None:
    with pytest.raises(HerdrTimeout):
        SubprocessRunner(binary(tmp_path, "sleep 5")).run(["x"], 0.2)


def test_a_binary_that_is_not_there_is_missing(tmp_path: Path) -> None:
    with pytest.raises(HerdrMissing):
        SubprocessRunner(str(tmp_path / "absent")).run(["x"], 1.0)
