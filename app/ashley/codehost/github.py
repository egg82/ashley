"""GitHub (REST) as a CodeHost, with a personal access token sent as a bearer: a fine-grained one with read-only
`Contents` and `Metadata` on the repositories she may read, or a classic one with `repo`. Project paths are
`owner/repo`. A repository listing has no server-side search, so `search` filters the page that came back."""

import json
from typing import Any

from . import addressing
from .config import CodeHostConfig
from .host import CodeHost, CodeHostFailed
from .model import Access, Entry, Fetched, Page, Project
from .wire import JSON_MAX, Call, Got, Wire, json_rows

API = "https://api.github.com"
_VERSION = "2022-11-28"


def _headers(access: Access, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {"Authorization": f"Bearer {access.token}", "Accept": accept, "X-GitHub-Api-Version": _VERSION}


def _repo(project: str) -> str:
    addressing.ensure("github", "project", project)
    return "/repos/" + addressing.encoded(project)


def _contents(project: str, ref: str, path: str) -> str:
    addressing.ensure("github", "ref", ref)
    addressing.ensure("github", "path", path)
    return _repo(project) + "/contents/" + addressing.encoded(path)


def _json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except ValueError as e:
        raise CodeHostFailed("unexpected") from e


class GitHubHost(CodeHost):
    def __init__(self, wire: Wire, config: CodeHostConfig) -> None:
        self._wire = wire
        self._config = config

    async def _get(self, access: Access, call: Call, project: str, path: str, params: dict[str, str | int],
                   cap: int = JSON_MAX, accept: str = "application/vnd.github+json", redirect: bool = False) -> Got:
        return await self._wire.get(access, call, project, access.base_url + path, params, _headers(access, accept), cap,
                                    redirect)

    async def check(self, access: Access) -> None:
        if not isinstance(_json((await self._get(access, "check", "", "/user", {})).body), dict):
            raise CodeHostFailed("unexpected")

    async def projects(self, access: Access, search: str) -> Page[Project]:
        params: dict[str, str | int] = {"per_page": self._config.projects_max, "sort": "pushed",
                                        "affiliation": "owner,collaborator,organization_member"}
        got = await self._get(access, "projects", "", "/user/repos", params)
        try:
            found = tuple(Project(int(r["id"]), str(r["full_name"]), str(r.get("description") or ""),
                                  r.get("default_branch")) for r in json_rows(got.body))
        except (KeyError, TypeError, ValueError) as e:
            raise CodeHostFailed("unexpected") from e
        wanted = search.lower()
        kept = tuple(p for p in found if wanted in p.path.lower() or wanted in p.description.lower())
        return Page(kept, got.next)

    async def tree(self, access: Access, project: str, ref: str, path: str) -> Page[Entry]:
        params: dict[str, str | int] = {"ref": ref} if ref else {}
        got = await self._get(access, "tree", project, _contents(project, ref, path), params)
        try:
            entries = tuple(Entry(str(r["path"]), "dir" if r["type"] == "dir" else "file")
                            for r in json_rows(got.body))
        except KeyError as e:
            raise CodeHostFailed("unexpected") from e
        return Page(entries[:self._config.tree_max], len(entries) > self._config.tree_max)

    async def file(self, access: Access, project: str, ref: str, path: str, max_bytes: int) -> Fetched:
        params: dict[str, str | int] = {"ref": ref} if ref else {}
        got = await self._get(access, "file", project, _contents(project, ref, path), params, max_bytes,
                              "application/vnd.github.raw+json")
        if got.json:
            raise CodeHostFailed("not_found")
        return Fetched(got.body, got.cut)

    async def archive(self, access: Access, project: str, ref: str) -> bytes:
        addressing.ensure("github", "ref", ref)
        got = await self._get(access, "archive", project, _repo(project) + "/zipball" + ("/" + addressing.encoded(ref) if ref else ""),
                              {}, self._config.snapshot_max_bytes, redirect=True)
        return got.body
