"""The adapters' archive (the zip, its cap, GitHub's signed redirect: https only, once, without the token), redirects
nowhere else, paths, projects and refs that climb or inject, and the one `codehost.get` log line."""

from collections.abc import Awaitable, Callable

import httpx2
import pytest
from ashley.codehost.host import CodeHost, CodeHostFailed, NullCodeHost
from ashley.codehost.model import Access, Forge
from hos_support import ALL_TOKENS, GH_ALANA, GL_ALANA, SMALL, access_for, all_logs, fields_of, go, log_text, zip_of
from hos_forges_support import Forges, standard
from hos_adapters_support import API_PREFIX, FORGES, HIDDEN, HOST, PROJECT, WEIRD, reason_of, run



# --- archive ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("forge", FORGES)
def test_an_archive_is_the_zip_the_forge_serves(forge: Forge) -> None:
    f = standard()
    snapshot = zip_of({"a.txt": b"hello", "b/c.txt": b"world"})
    (f.gitlab if forge == "gitlab" else f.github)[PROJECT[forge]].archive = snapshot

    async def scenario(host: CodeHost, access: Access, forges: Forges) -> None:
        assert await host.archive(access, PROJECT[forge], "") == snapshot
        assert await host.archive(access, PROJECT[forge], "main") == snapshot
        assert await reason_of(host.archive(access, PROJECT[forge], "no-such-ref")) == "not_found"
        assert await reason_of(host.archive(access, HIDDEN[forge], "")) == "not_found"

    run(forge, scenario, f)


@pytest.mark.parametrize("forge", FORGES)
def test_an_archive_at_the_cap_is_taken_and_one_byte_over_is_too_large(forge: Forge) -> None:
    f = standard()
    repo = (f.gitlab if forge == "gitlab" else f.github)[PROJECT[forge]]
    repo.archive = b"P" * SMALL.snapshot_max_bytes

    async def scenario(host: CodeHost, access: Access, forges: Forges) -> None:
        assert len(await host.archive(access, PROJECT[forge], "")) == SMALL.snapshot_max_bytes
        repo.archive = b"P" * (SMALL.snapshot_max_bytes + 1)
        assert await reason_of(host.archive(access, PROJECT[forge], "")) == "too_large"
        repo.archive = b"P" * (SMALL.snapshot_max_bytes * 50)
        assert await reason_of(host.archive(access, PROJECT[forge], "")) == "too_large"

    run(forge, scenario, f)


def test_github_zipball_is_followed_once_to_https_without_the_token() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        got = await host.archive(access, "alana/site", "")
        assert got == f.github["alana/site"].archive

    f = run("github", scenario)
    load = f.to("codeload.github.com")
    assert len(load) == 1
    assert not {"authorization", "private-token", "cookie"} & set(load[0].headers)
    assert GH_ALANA not in load[0].url_text() and not any(t in str(load[0].headers) for t in ALL_TOKENS)
    assert all(s.headers.get("authorization") == f"Bearer {GH_ALANA}" for s in f.to("api.github.com"))


def test_github_zipball_to_a_plain_http_address_is_refused_and_never_requested() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        with pytest.raises(CodeHostFailed):
            await host.archive(access, "alana/site", "")

    f = standard()
    f.script.append(("api.github.com", "/repos/alana/site/zipball", lambda r: httpx2.Response(
        302, headers={"location": "http://codeload.github.com/alana/site/legacy.zip/main?token=abc"})))
    f = run("github", scenario, f)
    assert f.to("codeload.github.com") == []


def test_github_zipball_is_followed_once_and_not_twice() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        with pytest.raises(CodeHostFailed):
            await host.archive(access, "alana/site", "")

    f = standard()
    f.script.append(("codeload.github.com", "/", lambda r: httpx2.Response(
        302, headers={"location": "https://elsewhere.test/zip"})))
    f = run("github", scenario, f)
    assert f.to("elsewhere.test") == [] and len(f.to("codeload.github.com")) == 1


@pytest.mark.parametrize("forge", FORGES)
@pytest.mark.parametrize("call", ["check", "projects", "tree", "file"])
def test_a_redirect_is_never_followed_where_none_was_asked_for(forge: Forge, call: str) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        p = PROJECT[forge]
        attempt: dict[str, Callable[[], Awaitable[object]]] = {
            "check": lambda: host.check(access), "projects": lambda: host.projects(access, ""),
            "tree": lambda: host.tree(access, p, "", ""), "file": lambda: host.file(access, p, "", "README.md", 100)}
        with pytest.raises(CodeHostFailed):
            await attempt[call]()

    f = standard()
    f.script.append((HOST[forge], API_PREFIX[forge], lambda r: httpx2.Response(
        302, headers={"location": "https://evil.test/steal"})))
    f = run(forge, scenario, f)
    assert f.to("evil.test") == []


@pytest.mark.parametrize("forge", FORGES)
def test_a_gitlab_or_github_that_redirects_a_zipball_off_to_http_is_not_followed(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        with pytest.raises(CodeHostFailed):
            await host.archive(access, PROJECT[forge], "")

    f = standard()
    f.script.append((HOST[forge], API_PREFIX[forge] if forge == "gitlab" else "/repos/", lambda r: httpx2.Response(
        302, headers={"location": "http://evil.test/zip"})))
    f = run(forge, scenario, f)
    assert f.to("evil.test") == []


# --- traversal and injection --------------------------------------------------------------------------------------

DOTS = ["../../../user", "..", "a/../../../../user", "src/../../x", "%2e%2e/%2e%2e/user", "./../user", "src/..%2f..%2fuser"]
def cases(values: list[str]) -> list[object]:
    return [pytest.param(f, v) for f in FORGES for v in values]


@pytest.mark.parametrize("forge, path", cases(DOTS))
def test_a_path_that_climbs_never_leaves_the_project(forge: Forge, path: str) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        for attempt in (host.tree(access, PROJECT[forge], "", path), host.file(access, PROJECT[forge], "", path, 100)):
            try:
                got = await attempt
            except CodeHostFailed:
                continue
            assert "someone" not in repr(got)

    f = run(forge, scenario)
    allowed = (f"/api/v4/projects/",) if forge == "gitlab" else (f"/repos/{PROJECT[forge]}/",)
    assert f.seen == [] or f.within(allowed) == []


@pytest.mark.parametrize("forge, project", cases(["../../user", "a/b/../../../../user",
                                                              "alana/site/../../../user", "..", "", "/"]))
def test_a_project_that_climbs_never_leaves_the_projects(forge: Forge, project: str) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        for attempt in (host.tree(access, project, "", ""), host.file(access, project, "", "README.md", 10),
                        host.archive(access, project, "")):
            with pytest.raises(CodeHostFailed):
                await attempt

    f = run(forge, scenario)
    allowed = ("/api/v4/projects/",) if forge == "gitlab" else ("/repos/",)
    assert f.within(allowed) == []


@pytest.mark.parametrize("forge, ref", cases(["main&path=src", "main#frag", "a b", "dev?ref=main", "../../user",
                                                      "main%26x=1"]))
def test_a_ref_is_one_value_and_never_a_second_parameter_or_a_path(forge: Forge, ref: str) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        for attempt in (host.tree(access, PROJECT[forge], ref, ""), host.file(access, PROJECT[forge], ref, "README.md", 10),
                        host.archive(access, PROJECT[forge], ref)):
            with pytest.raises(CodeHostFailed):
                await attempt

    f = run(forge, scenario)
    allowed = (f"/api/v4/projects/",) if forge == "gitlab" else (f"/repos/{PROJECT[forge]}/",)
    assert f.within(allowed) == []
    for s in f.seen:
        stray = set(s.query) - {"ref", "sha", "path", "per_page", "page", "recursive", "pagination", "order_by", "sort",
                                "membership", "search", "simple", "affiliation", "visibility", "archived", "owned",
                                "min_access_level", "statistics", "with_custom_attributes"}
        assert not stray, stray


# --- the log ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("forge", FORGES)
def test_each_call_logs_one_line_of_ids_and_counts_and_no_secret(forge: Forge, caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)

    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        await host.check(access)
        await host.projects(access, "")
        await host.tree(access, PROJECT[forge], "", "src")
        await host.file(access, PROJECT[forge], "", WEIRD, 1000)
        await host.archive(access, PROJECT[forge], "")
        with pytest.raises(CodeHostFailed):
            await host.file(access, PROJECT[forge], "", "src/app.py-missing", 10)

    run(forge, scenario)
    lines = fields_of(caplog, "codehost.get")
    assert {"check", "projects", "tree", "file", "archive"} <= {str(x.get("call")) for x in lines}
    for line in lines:
        assert {"forge", "call", "status", "bytes", "duration_ms"} <= set(line)
        assert line["forge"] == forge
    everywhere, hers = log_text(caplog), log_text(caplog, "ashley")
    assert not [t for t in ALL_TOKENS if t in everywhere]
    for secret in ("SIGNED-DOWNLOAD-SIGNATURE", "codeload", "unicode body", "weird dir", "app.py-missing", "src/app.py",
                   "README", "gitlab.test", "api.github.com"):
        assert secret not in hers, secret
    ok = [x for x in lines if x["call"] == "file" and x["status"] == 200]
    assert ok and isinstance(ok[0]["bytes"], int) and ok[0]["bytes"] >= 1
    assert any(x["status"] == 404 for x in lines)


def test_a_routed_host_sends_each_call_to_the_adapter_of_the_forge() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        await host.check(access_for("gitlab", GL_ALANA))
        await host.check(access_for("github", GH_ALANA))

    f = run("gitlab", scenario)
    assert {s.host for s in f.seen} == {"gitlab.test", "api.github.com"}


def test_the_null_host_fails_every_call() -> None:
    async def scenario() -> None:
        host = CodeHost.null()
        assert isinstance(host, NullCodeHost)
        a = access_for("gitlab", GL_ALANA)
        for attempt in (host.check(a), host.projects(a, ""), host.tree(a, "p", "", ""), host.file(a, "p", "", "f", 1),
                        host.archive(a, "p", "")):
            with pytest.raises(CodeHostFailed):
                await attempt

    go(scenario())
