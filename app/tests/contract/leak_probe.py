"""Driven by `test_contract_locator.py` in a nested pytest session; not collected on its own (`LEAK_PROBE` unset skips)."""

import os
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest
from ashley import services
from ashley.db.database import Database, DatabaseUnavailable, NullDatabase, Probe
from psycopg import AsyncConnection

pytestmark = pytest.mark.skipif(not os.environ.get("LEAK_PROBE"), reason="child probe")


class Wired(Database):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    async def probe(self) -> Probe:
        return Probe(reachable=True, writable=True)
    def connection(self) -> AbstractAsyncContextManager[AsyncConnection[tuple[Any, ...]]]:
        raise DatabaseUnavailable("a fake has no connections")


def test_a_registers() -> None:
    services.register(Database, Wired())
    assert isinstance(services.get(Database), Wired)


def test_b_sees_the_null_object() -> None:
    assert isinstance(services.get(Database), NullDatabase)
