"""The two probes, through the real app and, for readiness, a real Postgres."""

from fastapi.testclient import TestClient

from ashley import services
from ashley.api.models import ErrorResponse, HealthResponse, ReadyResponse
from ashley.db.database import Database
from ashley.db.migrate import migrate
from ashley.db.pool import PoolDatabase
from ashley.main import create_app
from ashley.settings import Settings

UNREACHABLE = "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1"


def app_for(url: str, version: str = "1.2.3") -> TestClient:
    app = create_app(Settings(database_url=url, build_version=version))
    services.register(Database, PoolDatabase(url, probe_timeout_s=0.3))
    return TestClient(app)


def test_health_reports_the_version_without_a_database() -> None:
    with app_for(UNREACHABLE, "9.9.9") as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert HealthResponse.model_validate(response.json()) == HealthResponse(status="ok", version="9.9.9")


def test_ready_is_503_with_the_declared_error_when_no_connection_opens() -> None:
    with app_for(UNREACHABLE) as client:
        response = client.get("/api/ready")
    assert response.status_code == 503
    assert ErrorResponse.model_validate(response.json()).code == "database_unavailable"


def test_ready_is_503_when_nothing_is_wired() -> None:
    client = TestClient(create_app(Settings(database_url="", build_version="x")))
    services.unregister(Database)
    assert client.get("/api/ready").status_code == 503


def test_ready_reports_a_writable_primary(empty_database: str) -> None:
    migrate(empty_database)
    with app_for(empty_database) as client:
        response = client.get("/api/ready")
    assert response.status_code == 200
    assert ReadyResponse.model_validate(response.json()) == ReadyResponse(ready=True, writable=True)


def test_an_unknown_api_path_is_404_not_the_client_page() -> None:
    with app_for(UNREACHABLE) as client:
        assert client.get("/api/nothing-here").status_code == 404
