"""The code host adapters (`ashley.codehost.gitlab.GitLabHost`, `github.GitHubHost`) over fake forges: projects, a
directory, a file cut at the cap, a snapshot, and the token's refusal, a missing project, a server error and a body
that is not the forge's all come back as `CodeHostFailed` with the reason; the token rides in the forge's header and
never into a log line; GitHub's snapshot follows its signed redirect without the token and refuses a non-https one;
every request made is a GET."""

import io
import json
import zipfile

import httpx2
import pytest
from ashley import logs
from ashley.codehost import config as codehost_config
from ashley.codehost.github import API, GitHubHost
from ashley.codehost.gitlab import GitLabHost
from ashley.codehost.host import CodeHost, CodeHostFailed, NullCodeHost
from ashley.codehost.model import Access, Forge as Kind
from ashley.codehost.routed import RoutedCodeHost
from ashley.codehost.wire import Wire
from codehost_support import TOKEN, FakeGitHub, FakeGitLab, Forge, repo_files
from files_support import sync

CONFIG = codehost_config.load()
LAB = "https://git.test"
PATH = "owner/ashley"


def host_over(fake: Forge, kind: Kind, config: codehost_config.CodeHostConfig = CONFIG) -> CodeHost:
    wire = Wire(httpx2.AsyncClient(transport=fake.transport(), follow_redirects=False), config.timeout_s)
    return GitLabHost(wire, config) if kind == "gitlab" else GitHubHost(wire, config)


def gitlab(config: codehost_config.CodeHostConfig = CONFIG) -> tuple[FakeGitLab, CodeHost, Access]:
    fake = FakeGitLab({PATH: repo_files(), "owner/other": {"a.txt": b"a"}})
    return fake, host_over(fake, "gitlab", config), Access("gitlab", LAB, TOKEN)


def github() -> tuple[FakeGitHub, CodeHost, Access]:
    fake = FakeGitHub({PATH: repo_files(), "owner/other": {"a.txt": b"a"}})
    return fake, host_over(fake, "github"), Access("github", API, TOKEN)


@sync
async def test_gitlab_lists_projects_a_directory_and_reads_a_file() -> None:
    fake, host, access = gitlab()
    await host.check(access)
    page = await host.projects(access, "")
    assert [p.path for p in page.items] == [PATH, "owner/other"] and page.more is False
    assert [p.path for p in (await host.projects(access, "other")).items] == ["owner/other"]
    tree = await host.tree(access, PATH, "", "deploy/esphome")
    assert [(e.path, e.kind) for e in tree.items] == [("deploy/esphome/m5stack-atom-echo.yaml", "file"),
                                                       ("deploy/esphome/wake-words", "dir")]
    got = await host.file(access, PATH, "", "deploy/esphome/m5stack-atom-echo.yaml", 1_000_000)
    assert got.data == repo_files()["deploy/esphome/m5stack-atom-echo.yaml"] and got.more is False
    raw = [p for _, p, _, _ in fake.seen if "files" in p]
    assert raw == ["/api/v4/projects/owner%2Fashley/repository/files/deploy%2Fesphome%2Fm5stack-atom-echo.yaml/raw"]
    assert {c for _, _, _, c in fake.seen} == {TOKEN} and {m for m, _, _, _ in fake.seen} == {"GET"}


@sync
async def test_github_lists_projects_a_directory_and_reads_a_file() -> None:
    fake, host, access = github()
    await host.check(access)
    assert [p.path for p in (await host.projects(access, "")).items] == [PATH, "owner/other"]
    assert [p.path for p in (await host.projects(access, "OTHER")).items] == ["owner/other"]
    tree = await host.tree(access, PATH, "", "deploy/esphome")
    assert [(e.path, e.kind) for e in tree.items] == [("deploy/esphome/m5stack-atom-echo.yaml", "file"),
                                                       ("deploy/esphome/wake-words", "dir")]
    got = await host.file(access, PATH, "main", "README.md", 1000)
    assert got.data == b"# ashley\n"
    assert {m for m, _, _, _ in fake.seen} == {"GET"}


@sync
async def test_a_file_is_cut_at_the_cap_and_says_so() -> None:
    for _, host, access in (gitlab(), github()):
        got = await host.file(access, PATH, "", "deploy/esphome/m5stack-atom-echo.yaml", 100)
        assert len(got.data) == 100 and got.more is True


@sync
async def test_a_snapshot_is_a_zip_and_one_over_the_cap_is_too_large() -> None:
    for fake, host, access in (gitlab(), github()):
        data = await host.archive(access, PATH, "main")
        assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == sorted(repo_files())
    small = codehost_config.parse({**_raw(), "snapshot_max_bytes": 100})
    kinds: list[tuple[Forge, Kind, Access]] = [(gitlab(small)[0], "gitlab", gitlab()[2]), (github()[0], "github", github()[2])]
    for fake, kind, access in kinds:
        with pytest.raises(CodeHostFailed) as e:
            await host_over(fake, kind, small).archive(access, PATH, "")
        assert e.value.reason == "too_large"


def _raw() -> dict[str, object]:
    loaded: dict[str, object] = json.loads(codehost_config.FILE.read_text())
    return loaded


@sync
async def test_github_follows_its_signed_redirect_without_the_token_and_refuses_a_plain_one() -> None:
    fake, host, access = github()
    await host.archive(access, PATH, "")
    api, signed = fake.seen[-2], fake.seen[-1]
    assert api[3] == TOKEN and signed[1].startswith("/signed/") and signed[3] == ""
    plain = httpx2.MockTransport(lambda r: httpx2.Response(302, headers={"location": "http://evil.test/x"}))
    wire = Wire(httpx2.AsyncClient(transport=plain, follow_redirects=False), 5)
    with pytest.raises(CodeHostFailed) as e:
        await GitHubHost(wire, CONFIG).archive(access, PATH, "")
    assert e.value.reason == "unexpected"


@sync
async def test_what_the_forge_says_comes_back_as_a_reason() -> None:
    for fake, host, access in (gitlab(), github()):
        for call, reason in ((host.projects(Access(access.forge, access.base_url, "wrong"), ""), "refused"),
                             (host.tree(access, "nobody/nothing", "", ""), "not_found")):
            with pytest.raises(CodeHostFailed) as e:
                await call
            assert e.value.reason == reason
        fake.down = 503
        with pytest.raises(CodeHostFailed) as e:
            await host.check(access)
        assert e.value.reason == "unreachable"
    odd = httpx2.MockTransport(lambda r: httpx2.Response(200, content=b"<html>"))
    for host in (GitLabHost(Wire(httpx2.AsyncClient(transport=odd), 5), CONFIG),
                 GitHubHost(Wire(httpx2.AsyncClient(transport=odd), 5), CONFIG)):
        with pytest.raises(CodeHostFailed) as e:
            await host.projects(Access("gitlab", LAB, TOKEN), "")
        assert e.value.reason == "unexpected"


@sync
async def test_the_token_and_the_paths_are_never_logged(capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    for _, host, access in (gitlab(), github()):
        await host.file(access, PATH, "", "deploy/esphome/m5stack-atom-echo.yaml", 1000)
        with pytest.raises(CodeHostFailed):
            await host.projects(Access(access.forge, access.base_url, "wrong-token-value"), "")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    assert sum("event=codehost.get" in ln for ln in lines) == 4 and any("call=file" in ln for ln in lines)
    assert any("status=401" in ln for ln in lines)
    assert not any(TOKEN in ln or "wrong-token-value" in ln or "m5stack" in ln or "git.test" in ln for ln in lines)
    assert TOKEN not in repr(Access("gitlab", LAB, TOKEN))


@sync
async def test_the_routed_host_sends_each_access_to_its_forge_and_the_null_one_fails() -> None:
    lab, github_ = gitlab(), github()
    routed = RoutedCodeHost({"gitlab": lab[1], "github": github_[1]})
    await routed.check(lab[2])
    await routed.check(github_[2])
    assert len(lab[0].seen) == 1 and len(github_[0].seen) == 1
    with pytest.raises(CodeHostFailed):
        await NullCodeHost().check(lab[2])


def test_the_host_can_only_read() -> None:
    reads = {"check", "projects", "tree", "file", "archive"}
    assert {n for n in vars(CodeHost) if not n.startswith("_") and n != "null"} == reads


def test_the_config_rejects_what_it_should() -> None:
    raw = _raw()
    for bad in ({**raw, "tree_max": 101}, {**raw, "timeout_s": 0}, {**raw, "read_bytes": "9"}, {**raw, "extra": 1},
                {k: v for k, v in raw.items() if k != "projects_max"}):
        with pytest.raises(ValueError):
            codehost_config.parse(bad)
    with pytest.raises(ValueError):
        codehost_config.parse([])
