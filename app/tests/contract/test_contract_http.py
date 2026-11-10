"""`/api/health` and `/api/ready` against the served contract (`openapi.json`)."""

from contextlib import AbstractAsyncContextManager
from typing import Any

import psycopg
import pytest
from ashley import services
from ashley.db.database import Database, DatabaseUnavailable, Probe
from contract_support import OPENAPI, client, declared_responses, unreachable_conninfo, violations
from hypothesis import given, settings
from hypothesis import strategies as st
from psycopg import AsyncConnection, sql


def test_the_contract_has_paths_to_test() -> None:
    assert set(OPENAPI["paths"]) >= {"/api/health", "/api/ready"}


def test_health_conforms_with_the_database_up(empty_database: str) -> None:
    with client(empty_database) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert violations(declared_responses("/api/health")["200"], r.json()) == []


def test_health_is_200_with_the_database_unreachable() -> None:
    with client(unreachable_conninfo()) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert violations(declared_responses("/api/health")["200"], r.json()) == []


@settings(max_examples=15, deadline=None)
@given(st.text(alphabet="0123456789.abcdef-+", min_size=1, max_size=20))
def test_health_reports_the_running_build(version: str) -> None:
    with client(unreachable_conninfo(), build_version=version) as c:
        assert c.get("/api/health").json()["version"] == version


def test_ready_conforms_with_a_writable_primary(empty_database: str) -> None:
    with client(empty_database) as c:
        r = c.get("/api/ready")
    assert r.status_code == 200
    body = r.json()
    assert violations(declared_responses("/api/ready")["200"], body) == []
    assert body == {"ready": True, "writable": True}


def test_ready_is_503_with_the_declared_error_when_the_database_is_unreachable() -> None:
    with client(unreachable_conninfo("canarypw")) as c:
        r = c.get("/api/ready")
    assert r.status_code == 503
    assert violations(declared_responses("/api/ready")["503"], r.json()) == []
    assert r.json()["code"] == "database_unavailable"
    for leaked in ("canarypw", "127.0.0.1"):
        assert leaked not in r.text


def test_ready_recovers_per_request_not_per_boot(empty_database: str) -> None:
    """Readiness reflects the database now: one app instance answers 200 against a good database, and an app aimed at
    a dead one answers 503 on every request, repeatedly."""
    with client(unreachable_conninfo()) as c:
        assert {c.get("/api/ready").status_code for _ in range(2)} == {503}
    with client(empty_database) as c:
        assert {c.get("/api/ready").status_code for _ in range(3)} == {200}


@pytest.mark.parametrize(("path", "method"), sorted((p, m) for p, item in OPENAPI["paths"].items() for m in item))
def test_every_declared_path_answers_only_declared_statuses(path: str, method: str, empty_database: str) -> None:
    declared = set(declared_responses(path, method))
    with (client(empty_database, follow_redirects=False) as up,
          client(unreachable_conninfo(), follow_redirects=False) as down):
        statuses = {str(up.request(method, path).status_code), str(down.request(method, path).status_code)}
    assert statuses <= declared


@pytest.mark.parametrize(
    "body",
    [{}, {"status": "ok"}, {"status": "ok", "version": 3}, {"status": "down", "version": "1"}, {"version": "1"}],
)
def test_the_validator_rejects_a_body_that_breaks_the_health_contract(body: dict[str, object]) -> None:
    assert violations(declared_responses("/api/health")["200"], body)


class FixedDatabase(Database):
    """A provider that answers a chosen probe, wired over the app's own through the locator."""

    def __init__(self, found: Probe) -> None:
        self.found = found

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def probe(self) -> Probe:
        return self.found

    def connection(self) -> AbstractAsyncContextManager[AsyncConnection[tuple[Any, ...]]]:
        raise DatabaseUnavailable("a fake has no connections")


@pytest.mark.parametrize("writable", [True, False])
def test_ready_reports_what_the_database_service_found(writable: bool) -> None:
    with client(unreachable_conninfo()) as c:
        services.register(Database, FixedDatabase(Probe(reachable=True, writable=writable)))
        r = c.get("/api/ready")
    assert r.status_code == 200
    assert r.json() == {"ready": True, "writable": writable}


def test_ready_is_503_whenever_the_database_service_is_unreachable() -> None:
    with client(unreachable_conninfo()) as c:
        services.register(Database, FixedDatabase(Probe(reachable=False, writable=False)))
        assert c.get("/api/ready").status_code == 503


def test_ready_reports_a_read_only_primary_as_not_writable(empty_database: str) -> None:
    with psycopg.connect(empty_database, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(
            sql.Identifier(str(conn.info.dbname))))
    with client(empty_database) as c:
        r = c.get("/api/ready")
    assert r.status_code == 200
    assert r.json() == {"ready": True, "writable": False}
