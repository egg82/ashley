"""Per-test time gate, a pytest plugin (`conftest.py` loads it): any test whose call phase uses more than CEILING_S of
CPU fails naming itself, so a slow test fails the day it appears. CPU seconds (this process and the children it waited
on), not wall: a loaded runner stretches wall time of fast tests, and a gate that cries wolf gets switched off. A
test that waits (a sleep, a lock, the network) uses little CPU and passes; wait-bound slowness is the timeout's.

Never raise the ceiling or hold a test to let it through: speed it up or split it. HELD lists node ids excused today,
may only shrink, and starts empty. Fixture setup is not timed, so build shared data there. TEST_CEILING_S raises the
ceiling for a deliberately slow scheduled run.

Judged only where TIME_GATE=1, which CI sets: on a workstation shared with other agents' runs, load alone moves a
fast test's CPU seconds past the ceiling (two whole runs elsewhere failed 6 and 4 different fast tests). Under
CI=true the gate must be on; `test_time_gate.py` fails otherwise, so it cannot be switched off there unnoticed."""

import os
from collections.abc import Generator

import pytest

CEILING_S = float(os.environ.get("TEST_CEILING_S", "1.0"))
HELD: frozenset[str] = frozenset()
CPU_KEY = pytest.StashKey[float]()


def cpu_now() -> float:
    t = os.times()
    return t.user + t.system + t.children_user + t.children_system


def enforced() -> bool:
    return os.environ.get("TIME_GATE") == "1"


def too_slow(nodeid: str, cpu_s: float) -> bool:
    return cpu_s > CEILING_S and nodeid not in HELD


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    start = cpu_now()
    try:
        return (yield)
    finally:
        item.stash[CPU_KEY] = cpu_now() - start


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    cpu_s = item.stash.get(CPU_KEY, None)
    if report.when == "call" and report.passed and cpu_s is not None and enforced() and too_slow(item.nodeid, cpu_s):
        report.outcome = "failed"
        report.longrepr = (
            f"{item.nodeid} used {cpu_s:.2f}s of CPU, over the {CEILING_S}s per-test ceiling "
            "(tests/time_gate.py): speed it up or split it"
        )
    return report
