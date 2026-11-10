"""Serves the built web client (`app/build/`, written by `npm run build` in `app/web`) at `/`."""

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

BUILD = Path(__file__).resolve().parents[2] / "build"


class ClientFiles(StaticFiles):
    """Files from the build; any other path outside `/api` gets `index.html`, so the client's own router handles it."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as e:
            if e.status_code != 404 or path.startswith("api/"):
                raise
            return await super().get_response("index.html", scope)


def mount_client(app: FastAPI, build: Path = BUILD) -> bool:
    """Mount the client when it has been built; False when there is nothing to serve."""
    if not (build / "index.html").is_file():
        return False
    app.mount("/", ClientFiles(directory=build, html=True), name="client")
    return True
