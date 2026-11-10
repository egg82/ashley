"""GitLab (REST v4) as a CodeHost: the token travels in `PRIVATE-TOKEN` and needs the scopes `read_api` and
`read_repository`. Project paths are `group/subgroup/name`."""

import json
from urllib.parse import quote

from . import addressing
from .config import CodeHostConfig
from .host import CodeHost, CodeHostFailed
from .model import Access, Entry, Fetched, Page, Project
from .wire import JSON_MAX, Call, Got, Wire, json_rows


def _headers(access: Access) -> dict[str, str]:
    return {"PRIVATE-TOKEN": access.token, "Accept": "application/json"}


def _project(path: str) -> str:
    addressing.ensure("gitlab", "project", path)
    return "/api/v4/projects/" + quote(path, safe="")


def _scoped(project: str, ref: str, path: str) -> str:
    addressing.ensure("gitlab", "ref", ref)
    addressing.ensure("gitlab", "path", path)
    return _project(project)


class GitLabHost(CodeHost):
    def __init__(self, wire: Wire, config: CodeHostConfig) -> None:
        self._wire = wire
        self._config = config

    async def _get(self, access: Access, call: Call, project: str, path: str, params: dict[str, str | int],
                   cap: int = JSON_MAX, headers: dict[str, str] | None = None) -> Got:
        return await self._wire.get(access, call, project, access.base_url + path, params, headers or _headers(access), cap)

    async def check(self, access: Access) -> None:
        body = (await self._get(access, "check", "", "/api/v4/user", {})).body
        try:
            ok = isinstance(json.loads(body), dict)
        except ValueError:
            ok = False
        if not ok:
            raise CodeHostFailed("unexpected")

    async def projects(self, access: Access, search: str) -> Page[Project]:
        params: dict[str, str | int] = {"membership": "true", "simple": "true", "order_by": "last_activity_at",
                                        "per_page": self._config.projects_max}
        if search:
            params["search"] = search
        got = await self._get(access, "projects", "", "/api/v4/projects", params)
        try:
            found = tuple(Project(int(r["id"]), str(r["path_with_namespace"]), str(r.get("description") or ""),
                                  r.get("default_branch")) for r in json_rows(got.body))
        except (KeyError, TypeError, ValueError) as e:
            raise CodeHostFailed("unexpected") from e
        return Page(found, got.next)

    async def tree(self, access: Access, project: str, ref: str, path: str) -> Page[Entry]:
        params: dict[str, str | int] = {"path": path, "per_page": self._config.tree_max}
        if ref:
            params["ref"] = ref
        got = await self._get(access, "tree", project, _scoped(project, ref, path) + "/repository/tree", params)
        try:
            entries = tuple(Entry(str(r["path"]), "dir" if r["type"] == "tree" else "file") for r in json_rows(got.body))
        except KeyError as e:
            raise CodeHostFailed("unexpected") from e
        return Page(entries, got.next)

    async def file(self, access: Access, project: str, ref: str, path: str, max_bytes: int) -> Fetched:
        url = _scoped(project, ref, path) + "/repository/files/" + quote(path, safe="") + "/raw"
        got = await self._get(access, "file", project, url, {"ref": ref or "HEAD"}, max_bytes,
                              {"PRIVATE-TOKEN": access.token})
        return Fetched(got.body, got.cut)

    async def archive(self, access: Access, project: str, ref: str) -> bytes:
        addressing.ensure("gitlab", "ref", ref)
        params: dict[str, str | int] = {"sha": ref} if ref else {}
        got = await self._get(access, "archive", project, _project(project) + "/repository/archive.zip", params,
                              self._config.snapshot_max_bytes, {"PRIVATE-TOKEN": access.token})
        return got.body
