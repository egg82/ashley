"""Per-test time gate, a pytest plugin (`conftest.py` loads it): any test whose setup + call + teardown takes more than
CEILING_S of wall clock fails naming itself, so a slow test fails the day it appears. Wall clock, and all three phases:
the gate this replaced timed only the call phase's CPU, so waits on production timeouts and work moved into fixtures
or teardown passed unseen.

One sample over the ceiling is not a verdict: a runner slowing every test in a shard at once put nine tests over it in
one run. A test that passed over the ceiling runs once more straight away, and fails only if it is over again; if it comes
in under, the margin readout names it with both timings. Speed is a budget, so a noisy sample is reported, not failed.

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
from _pytest.runner import runtestprotocol

from time_gate_held import HELD, HELD_SHARED

CEILING_S = float(os.environ.get("TEST_CEILING_S", "2.0"))
SHARED_CEILING_S = float(os.environ.get("TEST_SHARED_CEILING_S", "10.0"))
SHARED_SCOPES = frozenset({"session", "package", "module"})
SPENT_KEY = pytest.StashKey[float]()
OVER_KEY = pytest.StashKey[float]()    # the charge of a first run over the ceiling, before any verdict
FIRST_KEY = pytest.StashKey[float]()   # set while a test is timed again: what its first run was charged
WALL_PROPERTY = "time_gate_wall_s"
FIRST_PROPERTY = "time_gate_first_s"
_shared_s = [0.0]   # wall seconds this worker has spent in shared fixtures
_shared_over: list[str] = []
_near: list[tuple[float, str]] = []   # (charge, nodeid) of each test over half the ceiling, seen by the controller
_retimed: list[tuple[float, float, str]] = []   # (first charge, second charge, nodeid) of each test that passed retimed


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


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> bool | None:
    """pytest's own protocol, except that a test which passed over the ceiling is run and judged once more before any
    of its reports are logged, so the first run leaves no trace but the readout."""
    item.stash[SPENT_KEY] = _shared_s[0]
    if not enforced():
        return None
    item.ihook.pytest_runtest_logstart(nodeid=item.nodeid, location=item.location)
    reports = runtestprotocol(item, nextitem=nextitem, log=False)
    first = item.stash.get(OVER_KEY, None)
    if first is not None and all(report.passed for report in reports):   # runtestprotocol sets fixtures up afresh
        item.stash[FIRST_KEY] = first
        item.stash[SPENT_KEY] = _shared_s[0]
        reports = runtestprotocol(item, nextitem=nextitem, log=False)
    for report in reports:
        item.ihook.pytest_runtest_logreport(report=report)
    item.ihook.pytest_runtest_logfinish(nodeid=item.nodeid, location=item.location)
    return True


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    item.stash[SPENT_KEY] = item.stash.get(SPENT_KEY, 0.0) + call.duration
    if report.when != "teardown" or not report.passed or not enforced():
        return report
    spent = item.stash[SPENT_KEY] - _shared_s[0]   # phases' wall time less the shared fixtures' seconds inside them
    report.user_properties.append((WALL_PROPERTY, spent))   # xdist carries it to the controller's margin readout
    over, _shared_over[:] = list(_shared_over), []
    first = item.stash.get(FIRST_KEY, None)
    if not too_slow(item.nodeid, spent):
        if first is not None:
            report.user_properties.append((FIRST_PROPERTY, first))
    elif first is None and not over:
        item.stash[OVER_KEY] = spent   # timed again before a verdict (pytest_runtest_protocol)
    else:
        took = f"{first:.2f}s, then {spent:.2f}s timed again," if first is not None else f"{spent:.2f}s"
        over.append(f"{item.nodeid} took {took} of wall clock, setup and teardown included")
    if over:
        report.outcome = "failed"
        report.longrepr = (f"{'; '.join(over)}: over the per-test ceiling of {CEILING_S}s or the shared-fixture "
                           f"ceiling of {SHARED_CEILING_S}s (tests/time_gate.py). Speed it up or split it")
    return report


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    for name, value in report.user_properties:
        if name == WALL_PROPERTY and isinstance(value, float) and value > CEILING_S / 2:
            _near.append((value, report.nodeid))
    first = dict(report.user_properties).get(FIRST_PROPERTY)
    wall = dict(report.user_properties).get(WALL_PROPERTY)
    if isinstance(first, float) and isinstance(wall, float):
        _retimed.append((first, wall, report.nodeid))


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """The margin, never a verdict: every judged test over half the ceiling, so one drifting toward it shows before it
    fails a run."""
    if not enforced():
        return
    terminalreporter.section("time gate margin")
    for spent, nodeid in sorted(_near, reverse=True):
        terminalreporter.write_line(f"{spent:5.2f}s {'held ' if nodeid in HELD else ''}{nodeid}")
    held = sum(nodeid in HELD for _, nodeid in _near)
    terminalreporter.write_line(f"{len(_near)} tests over half the {CEILING_S}s ceiling, {held} of them held")
    for first, spent, nodeid in sorted(_retimed, reverse=True):
        terminalreporter.write_line(f"{first:5.2f}s, then {spent:.2f}s timed again: {nodeid}")
    terminalreporter.write_line(f"{len(_retimed)} tests over the ceiling once and under it timed again")
