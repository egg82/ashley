import gc
import itertools
from collections.abc import Coroutine, Generator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import HealthCheck, find, settings
from hypothesis import strategies as st

from ashley import main, services
from ashley.connections.kinds import ConnectionKinds
from ashley.ledger.ledger import Ledger
from ashley.settings import Settings
from ashley.sure.ledger import SureLedger
from ashley.wiring import CONNECTION_KINDS
from pg import throwaway_database
from source_tree import Parsed, parse_tree

pytest_plugins = ["time_gate", "pytester"]

# Wall-clock judgements of Hypothesis (200 ms per example, "input generation is slow") fail a fast test on a busy host
# for reasons that say nothing about the code; the CPU time gate is what bounds a test's cost.
settings.register_profile("ashley", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("ashley")


TESTS_RUN = itertools.count(1)
SWEEP_EVERY = 25  # tests between untimed collections: the cycles a test leaves (its app, its pool) are swept after a few dozen


@pytest.fixture(scope="session", autouse=True)
def hypothesis_warm() -> None:
    """Hypothesis builds its Unicode tables on the first text it generates, about 0.85 s of CPU from a cold
    `.hypothesis` directory, which is how CI always starts. Paid here, untimed, rather than charged by the time gate to
    whichever text-generating test runs first."""
    find(st.text(min_size=1), lambda s: s.strip() != "")


@pytest.fixture(scope="session", autouse=True)
def collector_warm() -> Generator[None]:
    """Everything imported and built so far (the app's framework, every test module) moves out of the collector's
    reach, and collection runs between tests (`unwired`) instead of inside one. Left automatic, whichever test trips a
    full pass is charged 0.3 s or more by the time gate, however trivial it is."""
    gc.collect()
    gc.freeze()
    gc.disable()
    yield
    gc.enable()


@pytest.fixture(scope="session")
def python_tree() -> dict[Path, Parsed]:
    """The Python source the structural gates read, parsed once for the session."""
    return parse_tree()


@pytest.fixture(autouse=True)
def unwired() -> Generator[None]:
    """Every test starts and ends with the locator empty, so Null Objects answer unless the test wires something; the
    connection kinds are declarations, not a service reaching out, and start registered.
    The collector is off at each test's start: a library that turns it back on (`collector_warm`) costs one test,
    not every test after it in the worker."""
    services.clear()
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    gc.disable()
    yield
    services.clear()
    if next(TESTS_RUN) % SWEEP_EVERY == 0:
        sweep()


def sweep() -> None:
    """Collect, then freeze what survived, so the next pass walks only what later tests made. Session caches (the
    structural gates' parsed tree alone is millions of objects) otherwise cost every full pass seconds. Frozen objects
    are still freed by their reference counts; only a cycle among them is never collected."""
    gc.collect()
    gc.freeze()


@pytest.fixture(autouse=True)
def no_background_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """An app a test starts (`create_app`) runs no singletons: without etcd they run under Postgres advisory locks, and
    would work on the very rows the test checks. A test of the singletons calls `wiring_singletons.singletons` itself."""
    def none(settings: Settings) -> list[Coroutine[Any, Any, None]]:
        return []

    monkeypatch.setattr(main, "wiring_singletons", SimpleNamespace(singletons=none))


@pytest.fixture
def connection_kinds_wired(unwired: None) -> None:
    """The production registry of connection kinds, for a test that asks which kinds exist."""
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))


@pytest.fixture
def sure_ledger_wired(unwired: None) -> None:
    """The Sure-backed Ledger, for a test that reads the household's money through it."""
    services.register(Ledger, SureLedger())


@pytest.fixture
def empty_database() -> Generator[str]:
    with throwaway_database() as url:
        yield url
