"""The GitLab and GitHub adapters of the CodeHost port, the real `Wire` and `RoutedCodeHost` over a fake HTTP server written
from the forges' public API documentation (`hos_support.Forges`): what each call answers, the failure reasons, the caps,
the token's place on the wire, redirects (https only, once, never carrying the token), path and ref traversal, and what the
one `codehost.get` log line holds."""

from dataclasses import replace

import httpx2
import pytest
from ashley.codehost.host import CodeHost, CodeHostFailed
from ashley.codehost.model import Access, Forge
from hos_support import GH_ALANA, GH_SAM, GITLAB, GL_ALANA, GL_SAM, SMALL, access_for
from hos_forges_support import Forges, Repo, many, standard
from hos_adapters_support import API_PREFIX, FORGES, HIDDEN, HOST, PROJECT, README, TOKEN, WEIRD, reason_of, run



# --- check --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("forge", FORGES)
def test_check_passes_for_a_token_the_host_knows(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await host.check(access) is None

    f = run(forge, scenario)
    assert len(f.seen) >= 1 and all(s.method == "GET" for s in f.seen)


@pytest.mark.parametrize("forge", FORGES)
def test_check_is_refused_for_a_token_the_host_turns_away(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await reason_of(host.check(access)) == "refused"

    run(forge, scenario, token="not-a-token-at-all")


@pytest.mark.parametrize("forge", FORGES)
def test_a_host_that_does_not_answer_is_unreachable(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await reason_of(host.check(access)) == "unreachable"
        assert await reason_of(host.projects(access, "")) == "unreachable"

    f = standard()
    f.down.add(HOST[forge])
    run(forge, scenario, f)
    f = standard()
    f.slow.add(HOST[forge])
    run(forge, scenario, f)


@pytest.mark.parametrize("forge", FORGES)
def test_a_server_error_is_a_failure_and_never_a_pass(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await reason_of(host.check(access)) in ("unreachable", "unexpected")

    f = standard()
    f.script.append((HOST[forge], API_PREFIX[forge], lambda r: httpx2.Response(503, text="maintenance")))
    run(forge, scenario, f)


@pytest.mark.parametrize("forge", FORGES)
def test_something_that_is_not_the_forge_is_not_a_pass(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await reason_of(host.check(access)) in ("unexpected", "not_found")

    f = standard()
    f.script.append((HOST[forge], API_PREFIX[forge], lambda r: httpx2.Response(
        200, content=b"<html>hello</html>", headers={"content-type": "text/html"})))
    run(forge, scenario, f)


@pytest.mark.parametrize("forge", FORGES)
@pytest.mark.parametrize("body", [b"[]", b'"hello"', b"3", b"null", b"true"])
def test_a_json_answer_that_is_not_an_object_is_not_a_pass(forge: Forge, body: bytes) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await reason_of(host.check(access)) in ("unexpected", "not_found")

    f = standard()
    f.script.append((HOST[forge], API_PREFIX[forge], lambda r: httpx2.Response(
        200, content=body, headers={"content-type": "application/json"})))
    run(forge, scenario, f)


# --- the token on the wire ----------------------------------------------------------------------------------------


def test_gitlab_sends_the_token_in_private_token_and_nowhere_in_the_address() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        await host.check(access)
        await host.projects(access, "proj")
        await host.tree(access, "grp/sub/proj", "", "src")
        await host.file(access, "grp/sub/proj", "", "README.md", 100)
        await host.archive(access, "grp/sub/proj", "")

    f = run("gitlab", scenario)
    assert f.seen and all(s.headers.get("private-token") == GL_ALANA for s in f.seen)
    assert GL_ALANA not in f.urls()


def test_github_sends_the_token_as_a_bearer_and_nowhere_in_the_address() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        await host.check(access)
        await host.projects(access, "site")
        await host.tree(access, "alana/site", "", "src")
        await host.file(access, "alana/site", "", "README.md", 100)
        await host.archive(access, "alana/site", "")

    f = run("github", scenario)
    api = f.to("api.github.com")
    assert api and all(s.headers.get("authorization") == f"Bearer {GH_ALANA}" for s in api)
    assert GH_ALANA not in f.urls()


def test_the_token_is_not_in_a_repr_or_in_a_failure() -> None:
    access = Access("gitlab", GITLAB, GL_ALANA)
    assert GL_ALANA not in repr(access) and GL_ALANA not in str(access)

    async def scenario(host: CodeHost, a: Access, f: Forges) -> None:
        try:
            await host.check(a)
        except CodeHostFailed as e:
            for shown in (repr(e), str(e), repr(e.args)):
                assert "bad-token-xyz" not in shown
            return
        raise AssertionError("no failure")

    run("gitlab", scenario, token="bad-token-xyz")


# --- projects -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("forge", FORGES)
def test_projects_are_those_the_token_reads_as_neutral_records(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        page = await host.projects(access, "")
        paths = {p.path for p in page.items}
        assert PROJECT[forge] in paths and HIDDEN[forge] not in paths and page.more is False
        mine = next(p for p in page.items if p.path == PROJECT[forge])
        repos = f.gitlab if forge == "gitlab" else f.github
        assert (mine.id, mine.default_branch) == (repos[mine.path].id, "main")
        assert mine.description == (repos[mine.path].description or "")
        assert not any(b"PRIVATE" in str(p).encode() for p in page.items)

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_each_token_reads_only_its_own_projects(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        mine = {p.path for p in (await host.projects(access, "")).items}
        sam = {p.path for p in (await host.projects(access_for(forge, GL_SAM if forge == "gitlab" else GH_SAM),
                                                    "")).items}
        assert HIDDEN[forge] in sam and HIDDEN[forge] not in mine and mine != sam
        assert "kim/other" not in mine | sam and "kim/kimrepo" not in mine | sam

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_a_search_narrows_the_projects(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        name = PROJECT[forge].rsplit("/", 1)[-1]
        assert [p.path for p in (await host.projects(access, name)).items] == [PROJECT[forge]]
        assert (await host.projects(access, "zzz-nothing-matches")).items == ()

    run(forge, scenario)


def test_a_project_with_no_default_branch_has_none() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        empty = next(p for p in (await host.projects(access, "")).items if p.path == "empty/repo")
        assert empty.default_branch is None and isinstance(empty.description, str)

    run("gitlab", scenario)


@pytest.mark.parametrize("forge", FORGES)
@pytest.mark.parametrize("n, more", [(4, False), (5, False), (6, True), (12, True)])
def test_projects_stop_at_the_cap_and_say_more_was_left(forge: Forge, n: int, more: bool) -> None:
    f = standard()
    repos = many(n)
    (f.gitlab if forge == "gitlab" else f.github).update(repos)
    (f.gitlab_tokens if forge == "gitlab" else f.github_tokens)[TOKEN[forge]] = set(repos)

    async def scenario(host: CodeHost, access: Access, forges: Forges) -> None:
        page = await host.projects(access, "")
        assert len(page.items) == min(n, SMALL.projects_max) and page.more is more
        assert len({p.path for p in page.items}) == len(page.items)

    run(forge, scenario, f)


# --- tree ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("forge", FORGES)
def test_the_tree_lists_what_is_directly_under_a_path(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        root = await host.tree(access, PROJECT[forge], "", "")
        got = {(e.path, e.kind) for e in root.items}
        assert {("src", "dir"), ("docs", "dir"), ("README.md", "file"), ("weird dir", "dir")} <= got
        assert ("src/app.py", "file") not in got and root.more is False
        under = await host.tree(access, PROJECT[forge], "main", "src")
        assert {(e.path, e.kind) for e in under.items} == {("src/app.py", "file"), ("src/util", "dir")}
        deeper = await host.tree(access, PROJECT[forge], "", "src/util")
        assert [(e.path, e.kind) for e in deeper.items] == [("src/util/helpers.py", "file")]

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_the_tree_reads_the_ref_asked_for_and_the_default_when_none(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert [e.path for e in (await host.tree(access, PROJECT[forge], "dev", "")).items] == ["dev.txt"]
        assert "README.md" in [e.path for e in (await host.tree(access, PROJECT[forge], "", "")).items]

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_the_tree_of_what_is_not_there_or_not_readable_is_not_found(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        for project, ref, path in ((PROJECT[forge], "", "nope/nothing"), (PROJECT[forge], "no-such-ref", ""),
                                   (HIDDEN[forge], "", ""), ("no/such-project", "", "")):
            assert await reason_of(host.tree(access, project, ref, path)) == "not_found"

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_the_tree_stops_at_the_cap_and_says_more_was_left(forge: Forge) -> None:
    f = standard()
    big = Repo("big/dir", 77, {"main": {f"d/f{i}.txt": b"x" for i in range(8)}})
    (f.gitlab if forge == "gitlab" else f.github)["big/dir"] = big
    (f.gitlab_tokens if forge == "gitlab" else f.github_tokens)[TOKEN[forge]].add("big/dir")

    async def scenario(host: CodeHost, access: Access, forges: Forges) -> None:
        page = await host.tree(access, "big/dir", "", "d")
        assert len(page.items) == SMALL.tree_max and page.more is True
        assert len({e.path for e in page.items}) == SMALL.tree_max and all(e.path.startswith("d/") for e in page.items)

    run(forge, scenario, f)


@pytest.mark.parametrize("forge", FORGES)
@pytest.mark.parametrize("n", [3, 5])
def test_a_directory_that_fits_the_cap_is_not_more(forge: Forge, n: int) -> None:
    f = standard()
    exact = Repo("big/dir", 77, {"main": {f"d/f{i}.txt": b"x" for i in range(n)}})
    (f.gitlab if forge == "gitlab" else f.github)["big/dir"] = exact
    (f.gitlab_tokens if forge == "gitlab" else f.github_tokens)[TOKEN[forge]].add("big/dir")

    async def scenario(host: CodeHost, access: Access, forges: Forges) -> None:
        page = await host.tree(access, "big/dir", "", "d")
        assert len(page.items) == n and page.more is False

    run(forge, scenario, f)


# --- file ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("forge", FORGES)
def test_a_file_is_its_bytes_and_a_cut_says_the_file_went_on(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        whole = await host.file(access, PROJECT[forge], "", "README.md", 1000)
        assert (whole.data, whole.more) == (README, False)
        exact = await host.file(access, PROJECT[forge], "main", "README.md", len(README))
        assert (exact.data, exact.more) == (README, False)
        cut = await host.file(access, PROJECT[forge], "", "README.md", 5)
        assert (cut.data, cut.more) == (README[:5], True)
        one_short = await host.file(access, PROJECT[forge], "", "README.md", len(README) - 1)
        assert (one_short.data, one_short.more) == (README[:-1], True)

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_a_binary_file_comes_back_byte_for_byte(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        got = await host.file(access, PROJECT[forge], "", "all.bin", 1000)
        assert got.data == bytes(range(256)) and got.more is False

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_a_path_with_spaces_unicode_and_reserved_characters_reaches_that_file(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        got = await host.file(access, PROJECT[forge], "", WEIRD, 1000)
        assert got.data == "unicode body ☃\n".encode()
        listed = await host.tree(access, PROJECT[forge], "", "weird dir")
        assert [e.path for e in listed.items] == [WEIRD]

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_the_file_of_the_ref_asked_for(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert (await host.file(access, PROJECT[forge], "dev", "dev.txt", 100)).data == b"on dev\n"
        assert await reason_of(host.file(access, PROJECT[forge], "", "dev.txt", 100)) == "not_found"

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_a_missing_or_hidden_path_is_a_failure_never_content(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await reason_of(host.file(access, PROJECT[forge], "", "nope.txt", 100)) == "not_found"
        assert await reason_of(host.file(access, HIDDEN[forge], "", "secret.txt", 100)) == "not_found"
        assert await reason_of(host.file(access, PROJECT[forge], "no-such-ref", "README.md", 100)) == "not_found"

    run(forge, scenario)


@pytest.mark.parametrize("forge", FORGES)
def test_a_directory_is_not_a_file(forge: Forge) -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        with pytest.raises(CodeHostFailed):
            await host.file(access, PROJECT[forge], "", "src", 100)

    run(forge, scenario)


def test_an_empty_file_is_empty_bytes_and_not_more() -> None:
    f = standard()
    for repos in (f.gitlab, f.github):
        for r in repos.values():
            for files in r.refs.values():
                files["empty.txt"] = b""

    async def scenario(host: CodeHost, access: Access, forges: Forges) -> None:
        got = await host.file(access, PROJECT["gitlab"], "", "empty.txt", 100)
        assert (got.data, got.more) == (b"", False)

    run("gitlab", scenario, f)

    async def scenario_gh(host: CodeHost, access: Access, forges: Forges) -> None:
        got = await host.file(access, PROJECT["github"], "", "empty.txt", 100)
        assert (got.data, got.more) == (b"", False)

    run("github", scenario_gh, f)


def test_an_empty_project_has_no_tree_and_no_file() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        assert await reason_of(host.tree(access, "empty/repo", "", "")) == "not_found"
        assert await reason_of(host.file(access, "empty/repo", "", "a.txt", 10)) == "not_found"

    run("gitlab", scenario)


def test_a_gitlab_served_under_a_path_is_reached_there() -> None:
    async def scenario(host: CodeHost, access: Access, f: Forges) -> None:
        under = replace(access, base_url=GITLAB + "/git")
        assert (await host.file(under, PROJECT["gitlab"], "", "README.md", 100)).data == README
        assert f.seen and all(s.raw.startswith("/git/api/v4/") for s in f.seen)

    run("gitlab", scenario)
