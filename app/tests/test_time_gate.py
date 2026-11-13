"""The per-test wall-clock ceiling (tests/time_gate.py) can fail: the verdict functions say so on both sides of their
ceilings, the hook is armed in this run, and real pytest runs go red on a test that waits, a slow fixture and a slow
teardown, name a slow shared fixture rather than the test that happened to reach it, and pass a fast test."""

import gc
import os
import subprocess
import sys
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
    assert time_gate.shared_too_slow("tree", time_gate.SHARED_CEILING_S + 0.01)


def test_under_the_ceiling_is_fine() -> None:
    assert not time_gate.too_slow("tests/x.py::t", time_gate.CEILING_S)
    assert not time_gate.shared_too_slow("tree", time_gate.SHARED_CEILING_S)


def test_ci_judges_with_the_gate_on() -> None:
    if os.environ.get("CI") != "true":
        pytest.skip("only CI must judge; a shared workstation's load moves wall time past the ceiling")
    assert time_gate.enforced(), "CI runs with TIME_GATE unset: no test is judged (set it in the CI workflow)"


def test_the_switch_reads_time_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIME_GATE", "1")
    assert time_gate.enforced()
    monkeypatch.setenv("TIME_GATE", "0")
    assert not time_gate.enforced()
    monkeypatch.delenv("TIME_GATE")
    assert not time_gate.enforced()


def test_a_held_entry_excuses_only_itself() -> None:
    for nodeid in time_gate.HELD:
        assert time_gate.too_slow(nodeid + "x", 99.0)
        assert not time_gate.too_slow(nodeid, 99.0)
    assert time_gate.too_slow("tests/x.py::not_held", 99.0)


def pytest_run(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "test_probe.py").write_text(body)
    # No plugin autoload: loading xdist, hypothesis and timeout is most of a child session's start.
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(TESTS), "TEST_CEILING_S": "0.4", "TEST_SHARED_CEILING_S": "0.6",
           "TIME_GATE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "time_gate", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), str(tmp_path)],
        capture_output=True, text=True, env=env, cwd=tmp_path, check=False)


SLOW_CASES = {
    "a wait in the body": "import time\n\ndef test_slow():\n    time.sleep(0.8)\n",
    "a slow fixture": "import time, pytest\n\n@pytest.fixture\ndef slow():\n    time.sleep(0.8)\n\ndef test_slow(slow):\n    pass\n",
    "a slow teardown": "import time, pytest\n\n@pytest.fixture\ndef slow():\n    yield\n    time.sleep(0.8)\n\ndef test_slow(slow):\n    pass\n",
    "phases each under the ceiling and over it together": ("import time, pytest\n\n@pytest.fixture\ndef slow():\n"
        "    time.sleep(0.25)\n    yield\n    time.sleep(0.25)\n\ndef test_slow(slow):\n    time.sleep(0.25)\n"),
}


@pytest.mark.parametrize("body", SLOW_CASES.values(), ids=SLOW_CASES.keys())
def test_a_real_run_fails_a_slow_test(tmp_path: Path, body: str) -> None:
    run = pytest_run(tmp_path, body)
    assert run.returncode == 1 and "per-test ceiling" in run.stdout and "test_slow took" in run.stdout, run.stdout


def test_a_shared_fixture_is_charged_by_name_not_to_the_test_that_reached_it(tmp_path: Path) -> None:
    body = ("import time, pytest\n\n@pytest.fixture(scope='session')\ndef tree():\n    time.sleep(0.2)\n\n"
            "def test_first(tree):\n    pass\n\ndef test_second(tree):\n    pass\n")
    under = pytest_run(tmp_path / "under", body)
    assert under.returncode == 0 and "2 passed" in under.stdout, under.stdout
    over = pytest_run(tmp_path / "over", body.replace("0.2", "0.9"))   # its own dir: a same-size rewrite reuses the .pyc
    assert over.returncode == 1 and "shared fixture tree took" in over.stdout, over.stdout
    assert "test_first took" not in over.stdout, over.stdout


def test_a_slow_test_after_a_shared_fixture_is_still_charged(tmp_path: Path) -> None:
    body = ("import time, pytest\n\n@pytest.fixture(scope='session')\ndef tree():\n    time.sleep(0.3)\n\n"
            "def test_first(tree):\n    pass\n\ndef test_slow(tree):\n    time.sleep(0.8)\n")
    run = pytest_run(tmp_path, body)
    assert run.returncode == 1 and "test_slow took" in run.stdout and "test_first took" not in run.stdout, run.stdout


def test_a_real_run_passes_a_fast_test(tmp_path: Path) -> None:
    fast = pytest_run(tmp_path, "def test_fast():\n    assert sum(range(1000)) == 499500\n")
    assert fast.returncode == 0 and "1 passed" in fast.stdout, fast.stdout
