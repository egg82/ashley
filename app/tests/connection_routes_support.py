"""The kind-keyed way suites drive the connection routes (connect or replace a kind, remove a kind), over the id-keyed
routes: list what the caller can see, then `PUT` the connection of that kind or `POST` a new one."""

from collections.abc import Mapping
from typing import Any

import httpx2
from starlette.testclient import TestClient


def _held(client: TestClient, kind: str) -> tuple[httpx2.Response, int | None]:
    listed = client.get("/api/connections")
    if listed.status_code != 200:
        return listed, None
    found: int | None = next((c["id"] for c in listed.json()["connections"] if c["kind"] == kind), None)
    return listed, found


def put_kind(client: TestClient, kind: str, json: Mapping[str, Any] | None = None,
             headers: Mapping[str, str] | None = None) -> httpx2.Response:
    """Replace the caller's connection of `kind`, or add one under the empty label."""
    listed, found = _held(client, kind)
    if listed.status_code != 200:
        return listed
    if found is None:
        made = client.post("/api/connections", json={"kind": kind, "label": "", **(json or {})}, headers=headers)
        made.status_code = 200 if made.status_code == 201 else made.status_code
        return made
    return client.put(f"/api/connections/{found}", json=json, headers=headers)


def delete_kind(client: TestClient, kind: str, headers: Mapping[str, str] | None = None) -> httpx2.Response:
    """Remove the caller's connection of `kind`; a request for one they have not got is a delete of an id none has."""
    listed, found = _held(client, kind)
    if listed.status_code != 200:
        return listed
    return client.delete(f"/api/connections/{0 if found is None else found}", headers=headers)
