"""The built web client is mounted last, so its catch-all never shadows an API route, whether or not `app/build/` exists."""

from pathlib import Path

import pytest
from ashley.main import create_app
from ashley.settings import Settings
from ashley.web.static import mount_client
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount


def built_client(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<html>client</html>")
    return tmp_path


def test_the_client_mount_is_the_last_route_of_the_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build = built_client(tmp_path)
    def mount_built(app: FastAPI) -> bool:
        return mount_client(app, build)
    monkeypatch.setattr("ashley.main.mount_client", mount_built)
    app = create_app(Settings(database_url="postgresql://unused", build_version="t"))
    last = app.router.routes[-1]
    assert isinstance(last, Mount) and last.name == "client"
    assert [r for r in app.router.routes if isinstance(r, Mount)] == [last]


def test_the_client_serves_pages_but_not_unknown_api_paths(tmp_path: Path) -> None:
    app = FastAPI()
    assert mount_client(app, built_client(tmp_path))
    c = TestClient(app)
    assert "client" in c.get("/memory").text
    assert c.get("/api/nothing").status_code == 404


def test_nothing_is_mounted_without_a_build(tmp_path: Path) -> None:
    assert not mount_client(FastAPI(), tmp_path)
