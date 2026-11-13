"""Per-test time gate, a pytest plugin (`conftest.py` loads it): any test whose setup + call + teardown takes more than
CEILING_S of wall clock fails naming itself, so a slow test fails the day it appears. Wall clock, and all three phases:
the gate this replaced timed only the call phase's CPU, so waits on production timeouts and work moved into fixtures
or teardown passed unseen.

A fixture shared across tests (session, package or module scope) is timed on its own, by name, against SHARED_CEILING_S:
under xdist which test reaches it first is chance, so charging the first user would fail a different test each run. A
test's charge leaves out the shared fixtures set up or torn down inside its phases. The CI job's timeout bounds the
total, shared fixtures included, and is all that bounds a shared fixture torn down after the session's last test.

Never raise a ceiling or hold a test to let one change through: speed it up or split it. HELD and HELD_SHARED
(`time_gate_held.py`) list what is excused today and may only shrink. TEST_CEILING_S raises the ceiling for a
deliberately slow scheduled run.

Judged only where TIME_GATE=1, which CI sets: wall clock on a workstation shared with other agents' runs measures the
load. Under CI=true the gate must be on; `test_time_gate.py` fails otherwise, so it cannot be switched off unnoticed."""

import os
import time
from collections.abc import Generator

import pytest

from time_gate_held import HELD, HELD_SHARED

CEILING_S = float(os.environ.get("TEST_CEILING_S", "2.0"))
SHARED_CEILING_S = float(os.environ.get("TEST_SHARED_CEILING_S", "10.0"))
SHARED_SCOPES = frozenset({"session", "package", "module"})
SPENT_KEY = pytest.StashKey[float]()
_shared_s = [0.0]   # wall seconds this worker has spent in shared fixtures
_shared_over: list[str] = []


def enforced() -> bool:
    return os.environ.get("TIME_GATE") == "1"


def too_slow(nodeid: str, wall_s: float) -> bool:
    return wall_s > CEILING_S and nodeid not in HELD


def shared_too_slow(name: str, wall_s: float) -> bool:
    return wall_s > SHARED_CEILING_S and name not in HELD_SHARED


def _note_shared(name: str, wall_s: float) -> None:
    _shared_s[0] += wall_s
    if shared_too_slow(name, wall_s):
        _shared_over.append(f"shared fixture {name} took {wall_s:.2f}s")


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[object]) -> Generator[None, object, object]:
    if fixturedef.scope not in SHARED_SCOPES:
        return (yield)
    down: list[float] = []
    fixturedef.addfinalizer(lambda: _note_shared(fixturedef.argname, time.perf_counter() - down[0]) if down else None)
    start = time.perf_counter()
    try:
        return (yield)
    finally:
        _note_shared(fixturedef.argname, time.perf_counter() - start)
        # Finalizers run last in, first out: this one runs first, marking where the fixture's own teardown starts.
        fixturedef.addfinalizer(lambda: down.append(time.perf_counter()))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    item.stash[SPENT_KEY] = -_shared_s[0]
    return (yield)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    item.stash[SPENT_KEY] = item.stash.get(SPENT_KEY, 0.0) + call.duration
    if report.when != "teardown" or not report.passed or not enforced():
        return report
    spent = item.stash[SPENT_KEY] - _shared_s[0]   # the shared fixtures' seconds inside this test's phases are left out
    over, _shared_over[:] = list(_shared_over), []
    if too_slow(item.nodeid, spent):
        over.append(f"{item.nodeid} took {spent:.2f}s of wall clock, setup and teardown included")
    if over:
        report.outcome = "failed"
        report.longrepr = (f"{'; '.join(over)}: over the per-test ceiling of {CEILING_S}s or the shared-fixture "
                           f"ceiling of {SHARED_CEILING_S}s (tests/time_gate.py). Speed it up or split it")
    return report
