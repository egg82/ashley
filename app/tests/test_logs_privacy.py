"""The logs reach Loki: ids, counts, kinds and durations only (`ashley/logs.py`). One run through the app with a planted
value in every place a person or a secret can reach it: none may appear in a line, and the lines that should exist
must, or the test proves nothing."""

import logging

import pytest
from fastapi.testclient import TestClient

from ashley import logs
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley import services
from ashley.main import create_app
from ashley.settings import Settings

ADDRESS = "203.0.113.77"
QUERY = "PLANTED-QUERY-zq"
PATH = "PLANTED-PATH-zq"
PASSWORD = "PLANTED-PASSWORD-zq"
HEADER = "PLANTED-HEADER-zq"
EXC = "PLANTED-EXC-zq"
URL = f"postgresql://nobody:{PASSWORD}@127.0.0.1:1/none?connect_timeout=1"


def lines(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith("ts=")]


def run_requests() -> None:
    logs.setup({"LOG_LEVEL": "debug"})
    app = create_app(Settings(database_url=URL, build_version="1"))
    services.register(Database, PoolDatabase(URL, probe_timeout_s=0.3))
    with TestClient(app, client=(ADDRESS, 50000)) as client:
        client.get("/api/health")
        client.get("/api/health")
        client.get(f"/api/ready?token={QUERY}", headers={"Authorization": f"Bearer {HEADER}"})
        client.get(f"/api/{PATH}?token={QUERY}")


def test_nothing_private_reaches_a_log_line(capsys: pytest.CaptureFixture[str]) -> None:
    run_requests()
    out = capsys.readouterr().out
    for planted in (ADDRESS, QUERY, PATH, PASSWORD, HEADER):
        assert planted not in out, f"{planted!r} reached the logs"
    requests = [ln for ln in lines(out) if "event=http.request" in ln]
    assert len(requests) == 2, "one line per request, and none for the health probe"
    assert "method=GET route=/api/ready status=503 ms=" in requests[0]
    assert "method=GET route=- status=404 ms=" in requests[1]
    assert "route=/api/health" not in out
    failed = [ln for ln in lines(out) if "event=db.probe_failed" in ln]
    assert len(failed) == 1 and "exc=" in failed[0] and "tb=" in failed[0], "the failure is logged as type and frames"
    assert all(ln.count(" ts=") == 0 for ln in lines(out)), "one event per line"


def test_this_test_can_fail(capsys: pytest.CaptureFixture[str]) -> None:
    """The control: a planted value logged on purpose is found, so a pass above means it was not there."""
    logs.setup({"LOG_LEVEL": "info"})
    logs.info(logging.getLogger("ashley.test"), "leak", note=QUERY)
    assert QUERY in capsys.readouterr().out


def test_an_exception_is_its_type_and_frames_never_its_message(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "info"})
    try:
        try:
            raise ValueError(EXC)
        except ValueError as e:
            raise RuntimeError(EXC + "2") from e
    except RuntimeError:
        logs.error(logging.getLogger("ashley.test"), "x.failed", exc=True, n=1)
    line = lines(capsys.readouterr().out)[0]
    assert EXC not in line and "exc=RuntimeError<ValueError" in line and "test_logs_privacy.py:" in line, line


def test_values_are_logfmt_safe(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "info"})
    logs.info(logging.getLogger("ashley.test"), "e.x", a="two words", b='q"uote', c="line\nbreak", d=None, e=True, f=1.23456)
    line = lines(capsys.readouterr().out)[0]
    assert 'a="two words"' in line and 'b="q\\"uote"' in line and 'c="line\\nbreak"' in line
    assert " d=" not in line and "e=true" in line and "f=1.23" in line


def test_the_servers_lifecycle_lines_keep_their_message(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "info"})
    logging.getLogger("uvicorn.error").info("Application startup complete.")
    assert 'event=log msg="Application startup complete."' in lines(capsys.readouterr().out)[0]


def test_a_library_line_carries_no_message(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup({"LOG_LEVEL": "info"})
    logging.getLogger("somelib").warning("connecting to %s", "postgresql://user:" + PASSWORD + "@host")
    line = lines(capsys.readouterr().out)[0]
    assert PASSWORD not in line and "event=log" in line
