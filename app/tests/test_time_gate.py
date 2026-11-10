"""The per-test CPU ceiling (tests/time_gate.py) can fail: the verdict function says so on both sides of the ceiling,
the hook is armed in this run, and a real pytest run of a busy test goes red while a sleeping one passes."""

import gc
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import time_gate

TESTS = Path(__file__).resolve().parent


def test_the_plugin_is_loaded_in_this_run(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.pluginmanager.has_plugin("time_gate"), "the gate is not registered: it would time nothing"


def test_the_collector_is_warmed_outside_the_tests() -> None:
    """A full collection pass over the imported framework costs 0.3 s or more, charged to whichever test trips it."""
    assert gc.get_freeze_count() > 10_000, "tests/conftest.py's collector_warm did not freeze the session's imports"
    assert not gc.isenabled(), "the collector runs inside tests again: whichever trips a full pass is charged for it"


def test_over_the_ceiling_is_slow() -> None:
    assert time_gate.too_slow("tests/x.py::t", time_gate.CEILING_S + 0.01)


def test_under_the_ceiling_is_fine() -> None:
    assert not time_gate.too_slow("tests/x.py::t", time_gate.CEILING_S)


def test_ci_judges_with_the_gate_on() -> None:
    if os.environ.get("CI") != "true":
        pytest.skip("only CI must judge; a shared workstation's load moves CPU seconds past the ceiling")
    assert time_gate.enforced(), "CI runs with TIME_GATE unset: no test is judged (set it in the CI workflow)"


def test_the_switch_reads_time_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIME_GATE", "1")
    assert time_gate.enforced()
    monkeypatch.setenv("TIME_GATE", "0")
    assert not time_gate.enforced()
    monkeypatch.delenv("TIME_GATE")
    assert not time_gate.enforced()


def test_waiting_is_not_cpu() -> None:
    start = time_gate.cpu_now()
    time.sleep(0.3)
    assert time_gate.cpu_now() - start < 0.1


def test_the_held_list_starts_empty_and_excuses_only_its_members() -> None:
    assert time_gate.HELD == frozenset()
    assert time_gate.too_slow("tests/x.py::t", 99.0)


def pytest_run(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    (tmp_path / "test_probe.py").write_text(body)
    # No plugin autoload: loading xdist, hypothesis and timeout is most of a child session's CPU.
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(TESTS), "TEST_CEILING_S": "0.15", "TIME_GATE": "1",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "time_gate", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), str(tmp_path)],
        capture_output=True, text=True, env=env, cwd=tmp_path, check=False)


def test_a_real_run_fails_a_busy_test(tmp_path: Path) -> None:
    busy = pytest_run(tmp_path, "import time_gate\n\ndef test_busy():\n    t = time_gate.cpu_now()\n    while time_gate.cpu_now() - t < 0.25:\n        pass\n")
    assert busy.returncode == 1 and "per-test ceiling" in busy.stdout and "test_busy" in busy.stdout, busy.stdout


def test_a_real_run_passes_a_waiting_test(tmp_path: Path) -> None:
    waiting = pytest_run(tmp_path, "import time\n\ndef test_waits():\n    time.sleep(0.6)\n")
    assert waiting.returncode == 0 and "1 passed" in waiting.stdout, waiting.stdout
