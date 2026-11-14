"""`ashley.web.serve`, the page's files alone for the `web` Deployment: the build's files, `index.html` for any other
page path, 404 for every server path, and no database, settings or environment behind it."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ashley.web.serve import NoBuild, create_web
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


def built_client(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>client</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "main.js").write_text("console.log('module')")
    return tmp_path


def test_it_serves_the_files_and_the_page_for_any_page_path(tmp_path: Path) -> None:
    c = TestClient(create_web(built_client(tmp_path)))
    for path in ("/", "/memory", "/rooms/workshop/bench/7"):
        r = c.get(path)
        assert (r.status_code, r.text) == (200, "<html>client</html>"), path
    assert c.get("/assets/main.js").text == "console.log('module')"


@pytest.mark.parametrize("path", ["/api", "/api/health", "/api/ready", "/api/auth/callback", "/privacy", "/terms"])
def test_it_serves_no_server_path(tmp_path: Path, path: str) -> None:
    assert TestClient(create_web(built_client(tmp_path))).get(path).status_code == 404


def test_it_refuses_to_start_without_a_build(tmp_path: Path) -> None:
    with pytest.raises(NoBuild):
        create_web(tmp_path)


def test_it_starts_with_no_environment_and_loads_no_database_code(tmp_path: Path) -> None:
    build = built_client(tmp_path)
    probe = ("import json, sys; from ashley.web.serve import create_web; "
             f"create_web(__import__('pathlib').Path({str(build)!r})); "
             "print(json.dumps(sorted(m for m in sys.modules if m.startswith('ashley'))))")
    run = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=20, cwd=ROOT,
                         env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)})
    assert run.returncode == 0, run.stderr
    loaded = json.loads(run.stdout.strip().splitlines()[-1])
    assert loaded == ["ashley", "ashley.logs", "ashley.web", "ashley.web.access", "ashley.web.serve", "ashley.web.server_paths",
                      "ashley.web.static"]


def request_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return [ln for ln in capsys.readouterr().out.splitlines() if "event=web.request" in ln]


def test_it_logs_one_line_per_request_without_the_query_or_the_caller(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    c = TestClient(create_web(built_client(tmp_path)))
    capsys.readouterr()
    c.get("/memory?token=s3cret", headers={"cookie": "sid=abc", "x-forwarded-for": "203.0.113.9"})
    c.get("/assets/main.js")
    c.get("/api/ready")
    lines = request_lines(capsys)
    assert len(lines) == 3
    assert "method=GET path=/memory status=200 bytes=19 duration_ms=" in lines[0]
    assert "path=/assets/main.js status=200 bytes=21" in lines[1]
    assert "path=/api/ready status=404" in lines[2]
    for secret in ("s3cret", "sid=abc", "203.0.113.9", "testclient"):
        assert all(secret not in ln for ln in lines)


def test_it_does_not_log_health_probes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    c = TestClient(create_web(built_client(tmp_path)))
    capsys.readouterr()
    c.get("/", headers={"user-agent": "kube-probe/1.31"})
    c.get("/api/health")
    c.get("/memory", headers={"user-agent": "Mozilla/5.0"})
    lines = request_lines(capsys)
    assert len(lines) == 1 and "path=/memory" in lines[0]
