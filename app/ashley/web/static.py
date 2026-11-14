"""Serves the built web client (`app/build/`, written by `npm run build` in `app/web`) at `/`."""

from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .server_paths import is_server_path

BUILD = Path(__file__).resolve().parents[2] / "build"


class ClientFiles(StaticFiles):
    """Files from the build; a server path (`ashley.web.server_paths`) is 404, and any other path that is not a file
    gets `index.html`, so the client's own router handles it."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        if is_server_path("/" + path):
            raise HTTPException(status_code=404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def mount_client(app: Starlette, build: Path = BUILD) -> bool:
    """Mount the client when it has been built; False when there is nothing to serve."""
    if not (build / "index.html").is_file():
        return False
    app.mount("/", ClientFiles(directory=build, html=True), name="client")
    return True
