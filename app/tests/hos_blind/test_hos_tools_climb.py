"""A path, a project or a ref in a tool call that climbs or injects never leaves the project."""


import pytest
from ashley.inference.model import ToolResult
from hos_support import GH_ALANA, GL_ALANA, go
from hos_tools_support import rig, use


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")



# --- a path or ref that climbs ------------------------------------------------------------------------------------

DOTS = ["../../../user", "..", "a/../../../../user", "src/../../x", "%2e%2e/%2e%2e/user", "./../user", "/etc/passwd",
        "src/..%2f..%2fuser", "..\\..\\user"]


@pytest.mark.parametrize("host, project, prefix", [("gitlab", "grp/sub/proj", "/api/v4/projects/"),
                                                    ("github", "alana/site", "/repos/alana/site/")])
@pytest.mark.parametrize("path", DOTS)
def test_a_path_that_climbs_never_leaves_the_project(db_url: str, host: str, project: str, prefix: str, path: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            t = r.tools(r.w.home, r.w.alana, await r.bench(r.w.home, r.w.alana))
            for name in ("git_tree", "git_read_file", "bench_add_from_git"):
                got = await use(t, name, host=host, project=project, path=path)
                assert isinstance(got, ToolResult) and "someone" not in got.content
            assert r.forges.within((prefix,)) == []

    go(scenario())


PROJECT_PARAMS = [pytest.param(h, pre, p)
                  for h, pre in (("gitlab", "/api/v4/projects/"), ("github", "/repos/"))
                  for p in ("../../user", "a/b/../../../../user", "..", "/", "alana/site/../../../user")]


@pytest.mark.parametrize("host, prefix, project", PROJECT_PARAMS)
def test_a_project_that_climbs_never_leaves_the_projects(db_url: str, host: str, prefix: str, project: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            t = r.tools(r.w.home, r.w.alana, await r.bench(r.w.home, r.w.alana))
            for name in ("git_tree", "git_read_file", "bench_add_from_git"):
                got = await use(t, name, host=host, project=project, path="README.md")
                assert got.is_error
            assert r.forges.within((prefix,)) == []

    go(scenario())


@pytest.mark.parametrize("host, project, prefix", [("gitlab", "grp/sub/proj", "/api/v4/projects/"),
                                                    ("github", "alana/site", "/repos/alana/site/")])
@pytest.mark.parametrize("ref", ["../../user", "..", "a/../../user"])
def test_a_snapshot_ref_that_climbs_never_leaves_the_project(db_url: str, host: str, project: str, prefix: str,
                                                              ref: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            t = r.tools(r.w.home, r.w.alana, await r.bench(r.w.home, r.w.alana))
            assert (await use(t, "bench_add_from_git", host=host, project=project, ref=ref)).is_error
            assert r.forges.within((prefix,)) == []

    go(scenario())


@pytest.mark.parametrize("host, project, prefix", [("gitlab", "grp/sub/proj", "/api/v4/projects/"),
                                                    ("github", "alana/site", "/repos/alana/site/")])
@pytest.mark.parametrize("ref", ["main&path=src", "main#frag", "a b", "dev?ref=main", "../../user", "main%26x=1",
                                 "main;id", "$(id)", "main\nX-Evil: 1"])
def test_a_ref_is_one_value_and_never_a_parameter_or_a_path(db_url: str, host: str, project: str, prefix: str,
                                                            ref: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            t = r.tools(r.w.home, r.w.alana, await r.bench(r.w.home, r.w.alana))
            for name in ("git_tree", "git_read_file", "bench_add_from_git"):
                got = await use(t, name, host=host, project=project, ref=ref, path="README.md")
                assert got.is_error
            assert r.forges.within((prefix,)) == []
            assert not [s for s in r.forges.seen if set(s.query) & {"x"} or "x-evil" in s.headers]

    go(scenario())
