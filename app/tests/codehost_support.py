"""Fake GitLab and GitHub APIs for `httpx2.MockTransport`, so the real adapters (`ashley.codehost.gitlab.GitLabHost`,
`ashley.codehost.github.GitHubHost`) run their HTTP with no network. Each serves projects holding files, answers only
to its token, and keeps what it was asked (`seen`: method, raw path, query, the credential header)."""

import io
import json
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, unquote

import httpx2

ESPHOME = Path(__file__).resolve().parents[2] / "deploy" / "esphome" / "m5stack-atom-echo.yaml"
TOKEN = "glpat-test-token-0123456789"  # gitleaks:allow (test fixture)
Files = dict[str, bytes]
Seen = list[tuple[str, str, dict[str, list[str]], str]]


def zipped(files: Files) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


def children(files: Files, path: str) -> list[tuple[str, str]]:
    """The (path, kind) entries directly under `path`."""
    prefix = path + "/" if path else ""
    found: dict[str, str] = {}
    for name in sorted(files):
        if name.startswith(prefix):
            head, _, rest = name[len(prefix):].partition("/")
            found[prefix + head] = "dir" if rest else "file"
    return sorted(found.items())


class Forge:
    """What both fakes share: `projects` by path, `down` (a status every call answers when set), `seen`."""

    def __init__(self, projects: dict[str, Files], token: str = TOKEN) -> None:
        self.projects = projects
        self.token = token
        self.down: int | None = None
        self.seen: Seen = []

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        raw = request.url.raw_path.decode().split("?")[0]
        query = parse_qs(request.url.query.decode())
        self.seen.append((request.method, raw, query, self.credential(request)))
        if request.method != "GET":
            return httpx2.Response(405)
        if self.down is not None:
            return httpx2.Response(self.down)
        if not self.authorized(request):
            return httpx2.Response(401, json={"message": "bad credentials"})
        return self.route(raw, query)

    def credential(self, request: httpx2.Request) -> str:
        raise NotImplementedError

    def authorized(self, request: httpx2.Request) -> bool:
        return self.credential(request) == self.expected()

    def expected(self) -> str:
        raise NotImplementedError

    def route(self, raw: str, query: dict[str, list[str]]) -> httpx2.Response:
        raise NotImplementedError


class FakeGitLab(Forge):
    def credential(self, request: httpx2.Request) -> str:
        return request.headers.get("private-token", "")

    def expected(self) -> str:
        return self.token

    def route(self, raw: str, query: dict[str, list[str]]) -> httpx2.Response:
        if raw == "/api/v4/user":
            return httpx2.Response(200, json={"id": 1, "username": "alana"})
        if raw == "/api/v4/projects":
            wanted = query.get("search", [""])[0]
            rows = [{"id": i + 1, "path_with_namespace": path, "description": f"the {path}", "default_branch": "main"}
                    for i, path in enumerate(self.projects) if wanted in path]
            return httpx2.Response(200, json=rows[:int(query["per_page"][0])],
                                   headers={"x-next-page": "2"} if len(rows) > int(query["per_page"][0]) else {})
        parts = raw.removeprefix("/api/v4/projects/").split("/", 1)
        files = self.projects.get(unquote(parts[0]))
        if files is None or len(parts) != 2:
            return httpx2.Response(404, json={"message": "404 Project Not Found"})
        rest = parts[1]
        if rest == "repository/tree":
            path = query.get("path", [""])[0]
            return httpx2.Response(200, json=[
                {"path": p, "name": p.rsplit("/", 1)[-1], "type": "tree" if k == "dir" else "blob"}
                for p, k in children(files, path)])
        if rest.startswith("repository/files/") and rest.endswith("/raw"):
            name = unquote(rest.removeprefix("repository/files/").removesuffix("/raw"))
            return httpx2.Response(200, content=files[name]) if name in files else httpx2.Response(404)
        if rest == "repository/archive.zip":
            return httpx2.Response(200, content=zipped(files), headers={"content-type": "application/zip"})
        return httpx2.Response(404)


class FakeGitHub(Forge):
    """Serves api.github.com; its zipball answers 302 to `codeload.github.com`, which this same fake serves unsigned."""

    def credential(self, request: httpx2.Request) -> str:
        return request.headers.get("authorization", "").removeprefix("Bearer ")

    def authorized(self, request: httpx2.Request) -> bool:
        return request.url.host == "codeload.github.com" or super().authorized(request)

    def expected(self) -> str:
        return self.token

    def route(self, raw: str, query: dict[str, list[str]]) -> httpx2.Response:
        if raw.startswith("/signed/"):
            return httpx2.Response(200, content=zipped(self.projects[unquote(raw.removeprefix("/signed/"))]))
        if raw == "/user":
            return httpx2.Response(200, json={"id": 1, "login": "alana"})
        if raw == "/user/repos":
            return httpx2.Response(200, json=[{"id": i + 1, "full_name": path, "description": f"the {path}",
                                               "default_branch": "main"} for i, path in enumerate(self.projects)])
        parts = raw.removeprefix("/repos/").split("/", 2)
        files = self.projects.get("/".join(parts[:2])) if len(parts) == 3 else None
        if files is None:
            return httpx2.Response(404, json=json.loads('{"message": "Not Found"}'))
        rest = unquote(parts[2])
        if rest.startswith("zipball"):
            return httpx2.Response(302, headers={"location": "https://codeload.github.com/signed/" + "/".join(parts[:2])})
        path = rest.removeprefix("contents/").strip("/")
        if path in files:
            return httpx2.Response(200, content=files[path])
        return httpx2.Response(200, json=[{"path": p, "name": p.rsplit("/", 1)[-1], "type": k}
                                          for p, k in children(files, path)])


def repo_files() -> Files:
    return {"deploy/esphome/m5stack-atom-echo.yaml": ESPHOME.read_bytes(), "README.md": b"# ashley\n",
            "deploy/esphome/wake-words/hey.json": b"{}"}
