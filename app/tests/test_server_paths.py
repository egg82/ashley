"""`ashley.web.server_paths` is what the app serves: every route of the app is a server path, and every entry of the
list has a route behind it, so the list the cluster's routing follows stays the code. A route outside the list fails
here; add it to the list, then to the cluster repo's `kustomization/ashley-app/patch-httproute.yaml` and
`patch-tunnel.yaml`, or the browser's request reaches `web` and gets 404."""

import pytest
from ashley.main import ROUTED
from ashley.web.server_paths import EXACT, PREFIXES, is_server_path
from starlette.routing import BaseRoute

MIN_ROUTES = 100


def app_paths() -> list[str]:
    """Every route path of every router the app includes (`ashley.main.ROUTED`, each included without a prefix)."""
    routes: list[BaseRoute] = [r for module in ROUTED for r in module.router.routes]
    return [path for r in routes if isinstance(path := getattr(r, "path", None), str)]


def test_every_route_of_the_app_is_a_server_path() -> None:
    paths = app_paths()
    assert len(paths) >= MIN_ROUTES
    assert [p for p in paths if not is_server_path(p)] == []


def test_every_listed_server_path_has_a_route() -> None:
    paths = app_paths()
    unused = [p for p in PREFIXES if not any(r == p or r.startswith(p + "/") for r in paths)]
    unused += [p for p in EXACT if p not in paths]
    assert unused == []


@pytest.mark.parametrize(("path", "served"), [
    ("/api", True), ("/api/health", True), ("/api/connections/oauth/google/callback", True),
    ("/privacy", True), ("/terms", True),
    ("/", False), ("/memory", False), ("/apis", False), ("/api.js", False), ("/privacy/more", False),
    ("/index.html", False),
])
def test_a_path_is_a_server_path_by_whole_segments(path: str, served: bool) -> None:
    assert is_server_path(path) is served
