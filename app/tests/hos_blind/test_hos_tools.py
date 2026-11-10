"""Her code host tools (`CodeHostTools`) on a real database and the fake forges: a person reads only through their own
connection (never a household-mate's, never another household's, whatever the arguments say), what an answer holds, the
errors that carry no argument value, a path or ref that climbs, and `bench_add_from_git` putting a file or a snapshot on
the person's own bench as a file piece."""


import json

import pytest
from ashley.inference.model import ToolResult
from hos_support import ALL_TOKENS, GH_ALANA, GH_KIM, GH_SAM, GL_ALANA, GL_KIM, GL_SAM, SMALL, all_logs, go, log_text
from hos_forges_support import standard
from hos_tools_support import GIT_TOOLS, asked, host_enum, rig, use


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")



# --- who is offered what ------------------------------------------------------------------------------------------


def test_a_person_with_no_connection_is_offered_nothing_even_when_housemates_have_one(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.kim, r.w.other, "github", GH_KIM)
            for household, person in ((r.w.home, r.w.lee), (r.w.home, r.w.sam)):
                assert (await r.tools(household, person).catalogue()).specs == ()

    go(scenario())


def test_the_catalogue_names_the_tools_and_the_connected_hosts(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.sam, r.w.home, "github", GH_SAM)
            await r.hold(r.w.sam, r.w.home, "gitlab", GL_SAM)
            one = (await r.tools(r.w.home, r.w.alana).catalogue()).specs
            assert {s.name for s in one} == GIT_TOOLS and all(s.reads for s in one)
            both = (await r.tools(r.w.home, r.w.sam).catalogue()).specs
            assert {s.name for s in both} == GIT_TOOLS
            assert all(set(host_enum(spec)) == {"gitlab", "github"} for spec in both)
            assert all("github" not in host_enum(spec) for spec in one)

    go(scenario())


def test_bench_add_from_git_is_offered_only_with_a_bench(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            names = {s.name for s in (await r.tools(r.w.home, r.w.alana, bench).catalogue()).specs}
            assert names == GIT_TOOLS | {"bench_add_from_git"}
            assert {s.name for s in (await r.tools(r.w.home, r.w.alana).catalogue()).specs} == GIT_TOOLS
            others = await r.tools(r.w.home, r.w.alana).call(asked("bench_add_from_git", host="gitlab", project="grp/sub/proj"))
            assert others.is_error and r.forges.seen == []

    go(scenario())


# --- one person's token, never another's --------------------------------------------------------------------------


def test_each_person_reads_through_their_own_token_and_sees_only_what_it_reads(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.sam, r.w.home, "gitlab", GL_SAM)
            alana, sam = r.tools(r.w.home, r.w.alana), r.tools(r.w.home, r.w.sam)
            mine = await use(alana, "git_projects", host="gitlab")
            assert not mine.is_error and "alana/private" in mine.content and "sam/notes" not in mine.content
            assert r.forges.credentials() == {GL_ALANA}
            theirs = await use(sam, "git_projects", host="gitlab")
            assert not theirs.is_error and "sam/notes" in theirs.content and "alana/private" not in theirs.content
            assert r.forges.credentials() == {GL_ALANA, GL_SAM}
            before = len(r.forges.seen)
            got = await use(alana, "git_read_file", host="gitlab", project="sam/notes", path="secret.txt")
            assert got.is_error and "SAM-GITLAB" not in got.content
            got = await use(alana, "git_tree", host="gitlab", project="sam/notes")
            assert got.is_error and "secret.txt" not in got.content
            assert {s.headers["private-token"] for s in r.forges.seen[before:]} <= {GL_ALANA}
            ok = await use(alana, "git_read_file", host="gitlab", project="alana/private", path="secret.txt")
            assert not ok.is_error and "ALANA-GITLAB-PRIVATE-CONTENT" in ok.content

    go(scenario())


def test_a_housemate_without_a_connection_reads_nothing_and_sends_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.sam, r.w.home, "github", GH_SAM)
            lee = r.tools(r.w.home, r.w.lee)
            for name, args in (("git_projects", {"host": "gitlab"}), ("git_projects", {"host": "github"}),
                               ("git_tree", {"host": "gitlab", "project": "alana/private"}),
                               ("git_read_file", {"host": "gitlab", "project": "alana/private", "path": "secret.txt"})):
                got = await use(lee, name, **args)
                assert got.is_error and "ALANA-GITLAB" not in got.content
            assert r.forges.seen == []

    go(scenario())


@pytest.mark.parametrize("name, args", [
    ("git_projects", {}),
    ("git_tree", {"project": "sam/samrepo"}),
    ("git_read_file", {"project": "sam/samrepo", "path": "secret.txt"})])
def test_a_host_the_person_did_not_connect_is_an_error_and_never_called_with_anothers_token(
        db_url: str, name: str, args: dict[str, object]) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.sam, r.w.home, "github", GH_SAM)
            got = await use(r.tools(r.w.home, r.w.alana), name, host="github", **args)
            assert got.is_error and "sam/samrepo" not in got.content and "SAM-GITHUB" not in got.content
            assert r.forges.to("api.github.com") == [] and GH_SAM not in r.forges.credentials()

    go(scenario())


def test_another_households_person_reads_their_own_and_none_of_this_households(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.kim, r.w.other, "gitlab", GL_KIM)
            kim = r.tools(r.w.other, r.w.kim)
            mine = await use(kim, "git_projects", host="gitlab")
            assert "kim/other" in mine.content and "alana/private" not in mine.content
            got = await use(kim, "git_read_file", host="gitlab", project="alana/private", path="secret.txt")
            assert got.is_error and "ALANA-GITLAB" not in got.content
            assert r.forges.credentials() == {GL_KIM}
            lost = r.tools(r.w.other, r.w.alana)
            assert (await lost.catalogue()).specs == ()
            assert (await use(lost, "git_projects", host="gitlab")).is_error and r.forges.credentials() == {GL_KIM}

    go(scenario())


@pytest.mark.parametrize("extra", [{"person_id": 0}, {"token": "glpat-sam-0002-SECRET"}, {"person": "sam"},  # gitleaks:allow (test fixture)
                                   {"base_url": "https://evil.test"}, {"url": "https://evil.test/x"},
                                   {"household_id": 0}, {"authorization": "Bearer glpat-sam-0002-SECRET"}])
def test_arguments_cannot_choose_whose_token_or_which_address(db_url: str, extra: dict[str, object]) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.sam, r.w.home, "gitlab", GL_SAM)
            args = {k: (r.w.sam if k == "person_id" else v) for k, v in extra.items()}
            got = await use(r.tools(r.w.home, r.w.alana), "git_projects", host="gitlab", **args)
            assert "sam/notes" not in got.content and "evil.test" not in got.content
            assert r.forges.credentials() <= {GL_ALANA} and r.forges.to("evil.test") == []
            assert {s.host for s in r.forges.seen} <= {"gitlab.test"}

    go(scenario())


# --- what an answer holds -----------------------------------------------------------------------------------------


def test_the_projects_tree_and_a_file_come_back_as_the_hosts_answered(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            t = r.tools(r.w.home, r.w.alana)
            got = await use(t, "git_projects", host="gitlab")
            assert not got.is_error and "grp/sub/proj" in got.content and "alana/site" not in got.content
            got = await use(t, "git_projects", host="github")
            assert not got.is_error and "alana/site" in got.content and "grp/sub/proj" not in got.content
            got = await use(t, "git_projects", host="gitlab", search="private")
            assert "alana/private" in got.content and "grp/sub/proj" not in got.content
            got = await use(t, "git_tree", host="github", project="alana/site", path="src")
            assert not got.is_error and "app.py" in got.content and "README.md" not in got.content
            got = await use(t, "git_tree", host="gitlab", project="grp/sub/proj", ref="dev")
            assert "dev.txt" in got.content and "README.md" not in got.content
            got = await use(t, "git_read_file", host="gitlab", project="grp/sub/proj", path="src/app.py")
            assert not got.is_error and "print('app')" in got.content
            got = await use(t, "git_read_file", host="github", project="alana/site", ref="dev", path="dev.txt")
            assert not got.is_error and "on dev" in got.content
            assert {s.method for s in r.forges.seen} == {"GET"}

    go(scenario())


def test_a_long_file_is_cut_and_never_shown_past_what_the_config_allows(db_url: str) -> None:
    f = standard()
    for repos in (f.gitlab, f.github):
        for repo in repos.values():
            if repo.refs.get("main") is not None and "README.md" in repo.refs["main"]:
                repo.refs["main"]["long.txt"] = b"A" * 500 + b"TAILMARK"
                repo.refs["main"]["mid.txt"] = b"B" * (SMALL.read_bytes + 10)

    async def scenario() -> None:
        async with rig(db_url, f) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            for host, project in (("gitlab", "grp/sub/proj"), ("github", "alana/site")):
                got = await use(r.tools(r.w.home, r.w.alana), "git_read_file", host=host, project=project, path="long.txt")
                assert not got.is_error and "AAAA" in got.content and "TAILMARK" not in got.content
                assert got.content.count("A") == SMALL.read_bytes and json.loads(got.content)["truncated"] is True
            short = await use(r.tools(r.w.home, r.w.alana), "git_read_file", host="gitlab", project="grp/sub/proj",
                              path="README.md")
            assert json.loads(short.content)["truncated"] is False
            mid = await use(r.tools(r.w.home, r.w.alana), "git_read_file", host="gitlab", project="grp/sub/proj",
                            path="mid.txt")
            assert mid.content.count("B") == SMALL.read_bytes and json.loads(mid.content)["truncated"] is True

    go(scenario())


def test_an_argument_the_tool_does_not_take_is_an_error_and_sends_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            t = r.tools(r.w.home, r.w.alana)
            assert (await use(t, "git_projects", host="gitlab", bogus="x")).is_error
            assert (await use(t, "git_tree", host="gitlab", project="grp/sub/proj", bogus=1)).is_error
            assert r.forges.seen == []

    go(scenario())


@pytest.mark.parametrize("length, sent", [(200, True), (201, False)])
def test_a_project_name_is_taken_to_the_length_the_tools_allow(db_url: str, length: int, sent: bool) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            got = await use(r.tools(r.w.home, r.w.alana), "git_tree", host="gitlab", project="g/" + "p" * (length - 2))
            assert got.is_error and bool(r.forges.seen) is sent

    go(scenario())


def test_a_binary_file_never_raises(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            got = await use(r.tools(r.w.home, r.w.alana), "git_read_file", host="gitlab", project="grp/sub/proj",
                            path="all.bin")
            assert isinstance(got, ToolResult)

    go(scenario())


@pytest.mark.parametrize("name", ["git_tree", "git_read_file", "bench_add_from_git", "git_push", "bench_read", ""])
def test_an_unknown_or_badly_called_tool_is_an_error_result(db_url: str, name: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            got = await use(r.tools(r.w.home, r.w.alana, None), name)
            assert got.is_error

    go(scenario())


BAD_ARGS: list[dict[str, object]] = [
    {"host": 5, "project": "grp/sub/proj", "path": "README.md"}, {"host": ["gitlab"], "project": "grp/sub/proj"},
    {"host": "gitlab", "project": 5, "path": "README.md"}, {"host": "gitlab", "project": ["a"], "path": "README.md"},
    {"host": "gitlab", "project": {"a": 1}, "path": "README.md"}, {"host": "gitlab", "project": None, "path": "README.md"},
    {"host": "gitlab", "project": "grp/sub/proj", "path": 7}, {"host": "gitlab", "project": "grp/sub/proj", "path": None},
    {"host": "gitlab", "project": "grp/sub/proj", "path": "README.md", "ref": 3},
    {"host": "gitlab", "project": "", "path": "README.md"}, {"host": "gitlab", "path": "README.md"},
    {"host": "gitlab", "project": "grp/sub/proj"}, {"host": "gitlab", "project": "grp/sub/proj", "path": ""},
    {"host": "gitlab", "project": "p" * 5000, "path": "README.md"}, {"host": "gitlab", "project": "grp/sub/proj",
                                                                    "path": "d/" * 5000},
    {"host": "bitbucket", "project": "a/b", "path": "c"},
]


@pytest.mark.parametrize("args", BAD_ARGS, ids=[str(i) for i in range(len(BAD_ARGS))])
def test_malformed_arguments_are_an_error_result_for_a_read_and_never_raise_for_any_tool(
        db_url: str, args: dict[str, object]) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            t = r.tools(r.w.home, r.w.alana, bench)
            for name in ("git_projects", "git_tree", "bench_add_from_git"):
                assert isinstance(await use(t, name, **args), ToolResult)
            assert (await use(t, "git_read_file", **args)).is_error

    go(scenario())


def test_bad_arguments_that_cannot_name_anything_send_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            t = r.tools(r.w.home, r.w.alana)
            for args in ({"host": "gitlab", "project": 5, "path": "x"}, {"host": 5, "project": "a/b", "path": "x"},
                         {"host": "bitbucket", "project": "a/b", "path": "x"}, {"host": "gitlab", "path": "x"}, {"host": "gitlab", "project": "a/b", "path": 3}):
                assert (await use(t, "git_read_file", **args)).is_error
            assert r.forges.seen == []

    go(scenario())


# --- errors carry no argument value, logs carry no content --------------------------------------------------------


def test_an_error_says_why_and_repeats_no_argument_value_or_token(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.sam, r.w.home, "github", "tok-revoked-SECRET-zzz")
            args = {"project": "zzz-Distinct/Proj-Q", "path": "Dist1nct/Path.txt", "ref": "Rf-1nstinct"}
            seen: list[ToolResult] = [
                await use(r.tools(r.w.home, r.w.alana), "git_read_file", host="gitlab", **args),
                await use(r.tools(r.w.home, r.w.alana), "git_tree", host="gitlab", **args),
                await use(r.tools(r.w.home, r.w.sam), "git_projects", host="github", search="S3arch-Distinct"),
                await use(r.tools(r.w.home, r.w.sam), "git_read_file", host="github", **args)]
            r.forges.down.add("gitlab.test")
            seen.append(await use(r.tools(r.w.home, r.w.alana), "git_read_file", host="gitlab", **args))
            for got in seen:
                assert got.is_error and got.content
                for value in ("Distinct", "Dist1nct", "Rf-1nstinct", "S3arch", "tok-revoked", "SECRET", "gitlab.test"):
                    assert value not in got.content, value
            assert len({g.content for g in seen}) >= 2

    go(scenario())


def test_the_logs_name_outcomes_and_never_content_paths_or_tokens(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    all_logs(caplog)

    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            t = r.tools(r.w.home, r.w.alana, bench)
            await use(t, "git_projects", host="gitlab", search="S3arch-private")
            await use(t, "git_tree", host="gitlab", project="grp/sub/proj", path="src")
            await use(t, "git_read_file", host="gitlab", project="grp/sub/proj", path="src/app.py")
            await use(t, "git_read_file", host="gitlab", project="grp/sub/proj", path="Missing/Dist1nct.txt")
            await use(t, "bench_add_from_git", host="gitlab", project="grp/sub/proj", path="README.md")

    go(scenario())
    everywhere, hers = log_text(caplog), log_text(caplog, "ashley")
    assert not [t for t in ALL_TOKENS if t in everywhere]
    for value in ("print('app')", "src/app.py", "Dist1nct", "S3arch", "hello", "gitlab.test"):
        assert value not in hers, value
    assert "tools.call" in hers
