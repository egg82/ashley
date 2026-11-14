"""The page's files alone, for the `web` Deployment: `uvicorn ashley.web.serve:create_web --factory --port 8080`.
Serves the built client as the app does (`ashley.web.static.ClientFiles`: deep paths get `index.html`, server paths are
404), and nothing else: no database, no settings and no environment, so the page loads while the app or its database is
down. Refuses to start when there is no build. Logs `web.start` with the count of files it serves."""

import logging
from pathlib import Path

from starlette.applications import Starlette

from .. import logs
from .static import BUILD, mount_client

log = logging.getLogger("ashley.web")


class NoBuild(RuntimeError):
    """There is no built client to serve."""


def create_web(build: Path = BUILD) -> Starlette:
    logs.setup()
    app = Starlette()
    if not mount_client(app, build):
        raise NoBuild(f"no index.html in {build}")
    logs.info(log, "web.start", files=sum(1 for p in build.rglob("*") if p.is_file()))
    return app
