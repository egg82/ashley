"""`bench_add_from_git` on the person's own bench, and the tools when connections, the store or the host are away."""


import pytest
from ashley import services
from ashley.codehost.host import CodeHost
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.model import Connection, Holder, Kind, Opened
from ashley.tools.tools import ToolsUnavailable
from ashley.workshop.model import Owner
from hos_support import DownStore, GH_ALANA, GL_ALANA, SMALL, go, zip_of
from hos_forges_support import Forges, standard
from hos_tools_support import PNG, rig, use


pytestmark = pytest.mark.usefixtures("connection_kinds_wired")



# --- bench_add_from_git -------------------------------------------------------------------------------------------


def with_files(f: Forges, **files: bytes) -> Forges:
    for repos in (f.gitlab, f.github):
        for repo in repos.values():
            if repo.refs.get("main") is not None and "README.md" in repo.refs["main"]:
                repo.refs["main"].update({k.replace("__", "."): v for k, v in files.items()})
    return f


def test_a_file_goes_on_the_bench_as_a_file_piece_and_is_kept(db_url: str) -> None:
    f = with_files(standard(), pic__png=PNG)

    async def scenario() -> None:
        async with rig(db_url, f) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            t = r.tools(r.w.home, r.w.alana, bench)
            for host, project in (("gitlab", "grp/sub/proj"), ("github", "alana/site")):
                got = await use(t, "bench_add_from_git", host=host, project=project, path="README.md")
                assert not got.is_error, got.content
            shown = await r.pieces(r.w.home, r.w.alana, bench)
            assert [k for k, _ in shown] == ["file", "file"] and all("README.md" in title for _, title in shown)
            assert b"# read me\nhello\n" in r.store.held.values()
            got = await use(t, "bench_add_from_git", host="gitlab", project="grp/sub/proj", path="pic.png")
            assert not got.is_error
            assert [k for k, _ in await r.pieces(r.w.home, r.w.alana, bench)] == ["file", "file", "image"]
            assert PNG in r.store.held.values()
            assert {s.method for s in r.forges.seen} == {"GET"}

    go(scenario())


def test_a_whole_project_goes_on_the_bench_as_its_zip(db_url: str) -> None:
    f = standard()
    snapshot = zip_of({"a.txt": b"hello", "b/c.txt": b"world"})
    f.gitlab["grp/sub/proj"].archive = snapshot
    f.github["alana/site"].archive = snapshot + b""

    async def scenario() -> None:
        async with rig(db_url, f) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            t = r.tools(r.w.home, r.w.alana, bench)
            for host, project in (("gitlab", "grp/sub/proj"), ("github", "alana/site")):
                got = await use(t, "bench_add_from_git", host=host, project=project)
                assert not got.is_error, got.content
            assert [k for k, _ in await r.pieces(r.w.home, r.w.alana, bench)] == ["file", "file"]
            assert snapshot in r.store.held.values()

    go(scenario())


@pytest.mark.parametrize("name, data", [("empty.txt", b""), ("all.bin", bytes(range(256))), ("fake.png", b"just text\n"),
                                        ("run.exe", b"MZ\x90\x00binary")])
def test_a_file_a_bench_does_not_take_adds_nothing(db_url: str, name: str, data: bytes) -> None:
    f = with_files(standard(), **{name.replace(".", "__"): data})

    async def scenario() -> None:
        async with rig(db_url, f) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            got = await use(r.tools(r.w.home, r.w.alana, bench), "bench_add_from_git", host="gitlab",
                            project="grp/sub/proj", path=name)
            assert got.is_error and name not in got.content
            assert await r.pieces(r.w.home, r.w.alana, bench) == [] and r.store.held == {}

    go(scenario())


def test_a_file_over_the_snapshot_cap_adds_nothing_and_is_not_cut_to_fit(db_url: str) -> None:
    f = with_files(standard(), big__txt=b"B" * (SMALL.snapshot_max_bytes + 1))

    async def scenario() -> None:
        async with rig(db_url, f) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            got = await use(r.tools(r.w.home, r.w.alana, bench), "bench_add_from_git", host="gitlab",
                            project="grp/sub/proj", path="big.txt")
            assert got.is_error
            assert await r.pieces(r.w.home, r.w.alana, bench) == [] and r.store.held == {}

    go(scenario())


def test_a_snapshot_over_the_cap_adds_nothing(db_url: str) -> None:
    f = standard()
    f.gitlab["grp/sub/proj"].archive = b"PK\x03\x04" + b"z" * (SMALL.snapshot_max_bytes + 10)

    async def scenario() -> None:
        async with rig(db_url, f) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            got = await use(r.tools(r.w.home, r.w.alana, bench), "bench_add_from_git", host="gitlab", project="grp/sub/proj")
            assert got.is_error
            assert await r.pieces(r.w.home, r.w.alana, bench) == [] and r.store.held == {}

    go(scenario())


def test_what_is_missing_hidden_or_unreachable_adds_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            t = r.tools(r.w.home, r.w.alana, bench)
            for args in ({"project": "grp/sub/proj", "path": "nope.txt"}, {"project": "sam/notes", "path": "secret.txt"},
                         {"project": "sam/notes"}, {"project": "grp/sub/proj", "ref": "no-such-ref"}):
                assert (await use(t, "bench_add_from_git", host="gitlab", **args)).is_error
            r.forges.down.add("gitlab.test")
            assert (await use(t, "bench_add_from_git", host="gitlab", project="grp/sub/proj", path="README.md")).is_error
            assert await r.pieces(r.w.home, r.w.alana, bench) == [] and r.store.held == {}

    go(scenario())


def test_another_persons_bench_takes_nothing_and_is_not_confirmed_to_exist(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            theirs = await r.bench(r.w.home, r.w.sam)
            theirs_elsewhere = await r.bench(r.w.other, r.w.kim)
            missing = max(theirs, theirs_elsewhere) + 100
            for bench in (theirs, theirs_elsewhere, missing):
                got = await use(r.tools(r.w.home, r.w.alana, bench), "bench_add_from_git", host="gitlab",
                                project="grp/sub/proj", path="README.md")
                assert got.is_error
            assert await r.pieces(r.w.home, r.w.sam, theirs) == []
            assert await r.pieces(r.w.other, r.w.kim, theirs_elsewhere) == []

    go(scenario())


def test_a_closed_bench_takes_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            await r.workshop.close(Owner(r.w.home, r.w.alana), bench)
            got = await use(r.tools(r.w.home, r.w.alana, bench), "bench_add_from_git", host="gitlab",
                            project="grp/sub/proj", path="README.md")
            assert got.is_error and await r.pieces(r.w.home, r.w.alana, bench) == []

    go(scenario())


def test_a_store_that_is_down_is_an_error_result_and_adds_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url, store=DownStore()) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            bench = await r.bench(r.w.home, r.w.alana)
            got = await use(r.tools(r.w.home, r.w.alana, bench), "bench_add_from_git", host="gitlab",
                            project="grp/sub/proj", path="README.md")
            assert got.is_error and await r.pieces(r.w.home, r.w.alana, bench) == []

    go(scenario())


# --- when the pieces fail -----------------------------------------------------------------------------------------


class Broken(Connections):
    def can_open(self) -> bool:
        return True

    async def add(self, household_id: int, kind: Kind, label: str, base_url: str, secret: str,
                  added_by: int, holder: Holder | None = None) -> Connection:
        raise ConnectionsUnavailable("down")

    async def replace(self, connection_id: int, household_id: int, person_id: int, base_url: str,
                      secret: str) -> Connection | None:
        raise ConnectionsUnavailable("down")

    async def relabel(self, connection_id: int, household_id: int, person_id: int,
                      label: str) -> Connection | None:
        raise ConnectionsUnavailable("down")

    async def seed(self, household_id: int, kind: Kind, base_url: str, secret: str) -> Connection | None:
        raise ConnectionsUnavailable("down")

    async def remove(self, connection_id: int, household_id: int, person_id: int | None) -> bool:
        raise ConnectionsUnavailable("down")

    async def answered(self, connection_id: int) -> None:
        raise ConnectionsUnavailable("down")

    async def of_household(self, household_id: int, person_id: int | None = None) -> tuple[Connection, ...]:
        raise ConnectionsUnavailable("down")

    async def opened(self, connection_id: int, household_id: int, person_id: int | None = None) -> Opened | None:
        raise ConnectionsUnavailable("down")


def test_connections_that_cannot_be_read_make_the_catalogue_unavailable_and_a_call_an_error(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            services.register(Connections, Broken())
            t = r.tools(r.w.home, r.w.alana)
            with pytest.raises(ToolsUnavailable):
                await t.catalogue()
            got = await use(t, "git_projects", host="gitlab")
            assert got.is_error and r.forges.seen == []

    go(scenario())


def test_an_unwired_code_host_is_an_error_result_not_a_raise(db_url: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            services.unregister(CodeHost)
            for name, args in (("git_projects", {}), ("git_tree", {"project": "a/b"}),
                               ("git_read_file", {"project": "a/b", "path": "c"})):
                assert (await use(r.tools(r.w.home, r.w.alana), name, host="gitlab", **args)).is_error

    go(scenario())


@pytest.mark.parametrize("host, project", [
    ("gitlab", "grp/sub/proj"),
    ("github", "alana/site")])
def test_reading_a_directory_as_a_file_is_an_error(db_url: str, host: str, project: str) -> None:
    async def scenario() -> None:
        async with rig(db_url) as r:
            await r.hold(r.w.alana, r.w.home, "gitlab", GL_ALANA)
            await r.hold(r.w.alana, r.w.home, "github", GH_ALANA)
            got = await use(r.tools(r.w.home, r.w.alana), "git_read_file", host=host, project=project, path="src")
            assert got.is_error and "util" not in got.content

    go(scenario())
