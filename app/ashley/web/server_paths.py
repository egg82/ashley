"""Which request paths the app serves; every other path is the page's files, which the `web` Deployment serves alone
(`ashley.web.serve`). The one list the cluster's routing follows: the cluster repo's
`kustomization/ashley-app/patch-httproute.yaml` and `patch-tunnel.yaml` send exactly these to `app`.
`tests/test_server_paths.py` holds every route of the app to it."""

PREFIXES = ("/api",)
"""Served by the app at the path itself and at every path under it."""

EXACT = ("/privacy", "/terms")
"""Served by the app at exactly this path."""


def is_server_path(path: str) -> bool:
    """True when the app, not the page's files, answers `path` (absolute, as it arrives)."""
    return path in EXACT or any(path == p or path.startswith(p + "/") for p in PREFIXES)
