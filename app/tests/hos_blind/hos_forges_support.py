"""The fake forges: GitLab and GitHub as one fake HTTP server written from the two forges' public REST documentation
behind `httpx2.MockTransport` (each token sees only its own projects; every request is recorded with its host, raw path,
query and headers; GitLab requires `ref` on a raw file, GitHub answers a zipball with a 302 to a signed codeload address),
and a real `RoutedCodeHost` over the real adapters and `Wire`."""

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, unquote

import httpx2
from ashley.codehost.config import CodeHostConfig
from ashley.codehost.github import GitHubHost
from ashley.codehost.gitlab import GitLabHost
from ashley.codehost.routed import RoutedCodeHost
from ashley.codehost.wire import Wire
from hos_support import CODELOAD, GH_ALANA, GH_KIM, GH_SAM, GITHUB_API, GL_ALANA, GL_KIM, GL_SAM, SMALL, zip_of



@dataclass
class Repo:
    """A project: files by ref, then by path. `description` and `default_branch` may be None, as a forge may send."""

    path: str
    id: int
    refs: dict[str, dict[str, bytes]]
    description: str | None = "a project"
    default_branch: str | None = "main"
    archive: bytes = field(default_factory=lambda: zip_of({"a.txt": b"hello"}))

    def files(self, ref: str) -> dict[str, bytes] | None:
        return self.refs.get(self.default_branch or "" if ref in ("", "HEAD") else ref)


def entries(files: dict[str, bytes], under: str) -> list[tuple[str, bool]]:
    """(path, is_dir) of what is directly under `under`, files sorted by path after directories."""
    prefix = under.strip("/") + "/" if under.strip("/") else ""
    seen: dict[str, bool] = {}
    for p in sorted(files):
        if p.startswith(prefix):
            first, _, rest = p[len(prefix):].partition("/")
            seen[prefix + first] = seen.get(prefix + first, False) or bool(rest)
    return sorted(seen.items(), key=lambda kv: (not kv[1], kv[0]))


@dataclass(frozen=True)
class Seen:
    host: str
    method: str
    raw: str
    query: dict[str, list[str]]
    headers: dict[str, str]

    @property
    def decoded(self) -> str:
        return unquote(self.raw)

    def normalized(self) -> str:
        """The raw path as a server that resolves `.` and `..` between literal slashes reads it."""
        out: list[str] = []
        for part in self.raw.split("/")[1:]:
            if part == "..":
                if out:
                    out.pop()
            elif part != ".":
                out.append(part)
        return "/" + "/".join(out)

    def url_text(self) -> str:
        return f"{self.host}{self.raw}?{json.dumps(self.query, sort_keys=True)}"


Handler = Callable[[httpx2.Request], httpx2.Response]


def _json(status: int, body: object, headers: dict[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json",
                                                                             **(headers or {})})


def _page(items: list[Any], query: dict[str, list[str]], link: Callable[[int], str]) -> tuple[list[Any], dict[str, str]]:
    per = min(int(query.get("per_page", ["30"])[0]), 100)
    page = int(query.get("page", ["1"])[0])
    chunk = items[(page - 1) * per: page * per]
    more = page * per < len(items)
    headers = {"x-page": str(page), "x-per-page": str(per), "x-next-page": str(page + 1) if more else "",
               "x-total": str(len(items)), "x-total-pages": str(-(-len(items) // per))}
    if more:
        headers["link"] = f'<{link(page + 1)}>; rel="next"'
    return chunk, headers


@dataclass
class Forges:
    """The fake forges. `gitlab` and `github` are the projects by path; `*_tokens` the paths each token reads. `script`
    is checked first: (host, path prefix, handler). `down` hosts refuse connections; `slow` hosts time out."""

    gitlab: dict[str, Repo] = field(default_factory=dict[str, Repo])
    github: dict[str, Repo] = field(default_factory=dict[str, Repo])
    gitlab_tokens: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    github_tokens: dict[str, set[str]] = field(default_factory=dict[str, set[str]])
    seen: list[Seen] = field(default_factory=list[Seen])
    script: list[tuple[str, str, Handler]] = field(default_factory=list[tuple[str, str, Handler]])
    down: set[str] = field(default_factory=set[str])
    slow: set[str] = field(default_factory=set[str])
    gitlab_hosts: set[str] = field(default_factory=lambda: {"gitlab.test"})

    # --- plumbing ------------------------------------------------------------------------------------------------

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        raw_full = request.url.raw_path.decode()
        raw, _, query_text = raw_full.partition("?")
        host = request.url.host
        self.seen.append(Seen(host, request.method, raw, parse_qs(query_text, keep_blank_values=True),
                              {k.lower(): v for k, v in request.headers.items()}))
        if host in self.down:
            raise httpx2.ConnectError("refused")
        if host in self.slow:
            raise httpx2.ReadTimeout("slow")
        decoded = unquote(raw)
        for h, prefix, fn in self.script:
            if h == host and decoded.startswith(prefix):
                return fn(request)
        query = parse_qs(query_text, keep_blank_values=True)
        if host == "api.github.com":
            return self._github(request, raw, query)
        if host == CODELOAD:
            return self._codeload(raw)
        if host in self.gitlab_hosts:
            return self._gitlab(request, raw, query)
        return _json(404, {"message": "no such host in the fake"})

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle), follow_redirects=False)

    def routed(self, config: CodeHostConfig = SMALL) -> RoutedCodeHost:
        wire = Wire(self.client(), config.timeout_s)
        return RoutedCodeHost({"gitlab": GitLabHost(wire, config), "github": GitHubHost(wire, config)})

    def to(self, host: str) -> list[Seen]:
        return [s for s in self.seen if s.host == host]

    def credentials(self) -> set[str]:
        """Every value of an authorization or private-token header any request carried."""
        return {v for s in self.seen for k, v in s.headers.items() if k in ("authorization", "private-token")}

    def urls(self) -> str:
        return "\n".join(s.url_text() for s in self.seen)

    def within(self, prefixes: tuple[str, ...]) -> list[Seen]:
        """The requests whose path, once resolved, is outside every one of `prefixes`."""
        return [s for s in self.seen if not any(s.normalized().startswith(p) for p in prefixes)]

    # --- GitLab (REST v4) ----------------------------------------------------------------------------------------

    def _gitlab(self, request: httpx2.Request, raw: str, query: dict[str, list[str]]) -> httpx2.Response:
        token = request.headers.get("private-token", "")
        if token not in self.gitlab_tokens:
            return _json(401, {"message": "401 Unauthorized"})
        visible = self.gitlab_tokens[token]
        i = raw.find("/api/v4/")
        if i < 0:
            return httpx2.Response(200, content=b"<html><body>a login page</body></html>",
                                   headers={"content-type": "text/html"})
        parts = [unquote(p) for p in raw[i + len("/api/v4/"):].split("/")]
        if parts == ["user"]:
            return _json(200, {"id": 1, "username": "someone"})
        origin = f"https://{request.url.host}{raw[:i]}/api/v4"
        if parts == ["projects"]:
            wanted = query.get("search", [""])[0].lower()
            rows = [r for p, r in self.gitlab.items() if p in visible and wanted in p.lower()]
            body = [{"id": r.id, "path_with_namespace": r.path, "description": r.description,
                     "default_branch": r.default_branch, "name": r.path.rsplit("/", 1)[-1]} for r in rows]
            chunk, headers = _page(body, query, lambda n: f"{origin}/projects?page={n}")
            return _json(200, chunk, headers)
        if len(parts) >= 3 and parts[0] == "projects":
            repo = next((r for p, r in self.gitlab.items() if p in visible and parts[1] in (p, str(r.id))), None)
            if repo is None:
                return _json(404, {"message": "404 Project Not Found"})
            return self._gitlab_repo(repo, parts[2:], query, origin)
        return _json(404, {"message": "404 Not Found"})

    def _gitlab_repo(self, repo: Repo, parts: list[str], query: dict[str, list[str]], origin: str) -> httpx2.Response:
        ref = query.get("ref", [""])[0]
        if parts == ["repository", "tree"]:
            files = repo.files(ref)
            under = query.get("path", [""])[0]
            found = entries(files, under) if files is not None else []
            if not found:
                return _json(404, {"message": "404 Tree Not Found"})
            rows = [{"id": "x", "name": p.rsplit("/", 1)[-1], "type": "tree" if d else "blob", "path": p,
                     "mode": "040000" if d else "100644"} for p, d in found]
            chunk, headers = _page(rows, query, lambda n: f"{origin}/projects/{repo.id}/repository/tree?page={n}")
            return _json(200, chunk, headers)
        if len(parts) == 4 and parts[:2] == ["repository", "files"] and parts[3] == "raw":
            if not ref:
                return _json(400, {"error": "ref is missing"})
            files = repo.files(ref)
            name = parts[2]
            if files is None or name not in files:
                return _json(404, {"message": "404 File Not Found"})
            return httpx2.Response(200, content=files[name], headers={"content-type": "application/octet-stream"})
        if parts in (["repository", "archive.zip"], ["repository", "archive"]):
            if repo.files(query.get("sha", [""])[0]) is None:
                return _json(404, {"message": "404 Commit Not Found"})
            return httpx2.Response(200, content=repo.archive, headers={"content-type": "application/zip"})
        return _json(404, {"message": "404 Not Found"})

    # --- GitHub (REST) -------------------------------------------------------------------------------------------

    def _github(self, request: httpx2.Request, raw: str, query: dict[str, list[str]]) -> httpx2.Response:
        auth = request.headers.get("authorization", "")
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        if token not in self.github_tokens:
            return _json(401, {"message": "Bad credentials"})
        visible = self.github_tokens[token]
        if raw == "/user":
            return _json(200, {"login": "someone", "id": 1})
        if raw == "/user/repos":
            rows = [{"id": r.id, "full_name": r.path, "description": r.description, "default_branch": r.default_branch,
                     "private": True} for p, r in self.github.items() if p in visible]
            chunk, headers = _page(rows, query, lambda n: f"{GITHUB_API}/user/repos?page={n}")
            return _json(200, chunk, headers)
        parts = [unquote(p) for p in raw.split("/")[1:]]
        if len(parts) >= 3 and parts[0] == "repos":
            repo = self.github.get(f"{parts[1]}/{parts[2]}")
            if repo is None or repo.path not in visible:
                return _json(404, {"message": "Not Found"})
            return self._github_repo(repo, parts[3:], query, request.headers.get("accept", ""))
        return _json(404, {"message": "Not Found"})

    def _github_repo(self, repo: Repo, parts: list[str], query: dict[str, list[str]], accept: str) -> httpx2.Response:
        if not parts:
            return _json(200, {"id": repo.id, "full_name": repo.path, "default_branch": repo.default_branch})
        if parts[0] == "zipball":
            ref = "/".join(parts[1:])
            if repo.files(ref) is None:
                return _json(404, {"message": "Not Found"})
            where = f"https://{CODELOAD}/{repo.path}/legacy.zip/refs/heads/{quote(ref or repo.default_branch or '')}"
            return httpx2.Response(302, headers={"location": where + "?token=SIGNED-DOWNLOAD-SIGNATURE-9f3"})
        if parts[0] == "contents":
            ref = query.get("ref", [""])[0]
            files = repo.files(ref)
            name = "/".join(parts[1:]).strip("/")
            if files is None:
                return _json(404, {"message": f"No commit found for the ref {ref}"})
            if name in files:
                if "raw" in accept:
                    return httpx2.Response(200, content=files[name], headers={"content-type": "application/vnd.github.raw"})
                return _json(200, {"type": "file", "name": name.rsplit("/", 1)[-1], "path": name,
                                   "size": len(files[name]), "encoding": "base64",
                                   "content": base64.encodebytes(files[name]).decode()})
            found = entries(files, name)
            if not found:
                return _json(404, {"message": "Not Found"})
            return _json(200, [{"name": p.rsplit("/", 1)[-1], "path": p, "type": "dir" if d else "file",
                                "size": 0 if d else len(files[p])} for p, d in found])
        return _json(404, {"message": "Not Found"})

    def _codeload(self, raw: str) -> httpx2.Response:
        parts = raw.split("/")[1:]
        if len(parts) < 3 or parts[2] != "legacy.zip":
            return _json(404, {"message": "Not Found"})
        repo = self.github.get(f"{parts[0]}/{parts[1]}")
        if repo is None:
            return _json(404, {"message": "Not Found"})
        return httpx2.Response(200, content=repo.archive, headers={"content-type": "application/zip"})


def standard() -> Forges:
    """Three people's projects on each forge, every project holding content only its readers may see."""
    main = {"README.md": b"# read me\nhello\n", "src/app.py": b"print('app')\n", "src/util/helpers.py": b"x = 1\n",
            "docs/guide.md": b"the guide\n", "weird dir/ünï #1?%.txt": "unicode body ☃\n".encode()}
    bin_all = bytes(range(256))
    f = Forges()
    f.gitlab = {
        "grp/sub/proj": Repo("grp/sub/proj", 11, {"main": {**main, "all.bin": bin_all}, "dev": {"dev.txt": b"on dev\n"}},
                             description=None),
        "alana/private": Repo("alana/private", 12, {"main": {"secret.txt": b"ALANA-GITLAB-PRIVATE-CONTENT"}}),
        "sam/notes": Repo("sam/notes", 13, {"main": {"secret.txt": b"SAM-GITLAB-PRIVATE-CONTENT"}}),
        "kim/other": Repo("kim/other", 14, {"main": {"secret.txt": b"KIM-GITLAB-PRIVATE-CONTENT"}}),
        "empty/repo": Repo("empty/repo", 15, {}, default_branch=None),
    }
    f.github = {
        "alana/site": Repo("alana/site", 21, {"main": {**main, "all.bin": bin_all}, "dev": {"dev.txt": b"on dev\n"}}),
        "sam/samrepo": Repo("sam/samrepo", 22, {"main": {"secret.txt": b"SAM-GITHUB-PRIVATE-CONTENT"}}),
        "kim/kimrepo": Repo("kim/kimrepo", 23, {"main": {"secret.txt": b"KIM-GITHUB-PRIVATE-CONTENT"}}),
    }
    f.gitlab_tokens = {GL_ALANA: {"grp/sub/proj", "alana/private", "empty/repo"}, GL_SAM: {"grp/sub/proj", "sam/notes"},
                       GL_KIM: {"kim/other"}}
    f.github_tokens = {GH_ALANA: {"alana/site"}, GH_SAM: {"sam/samrepo"}, GH_KIM: {"kim/kimrepo"}}
    return f


def many(n: int, prefix: str = "bulk") -> dict[str, Repo]:
    return {f"{prefix}/r{i:03d}": Repo(f"{prefix}/r{i:03d}", 1000 + i, {"main": {f"f{j:03d}.txt": b"x" for j in range(n)}})
            for i in range(n)}

