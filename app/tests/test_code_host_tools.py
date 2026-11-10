"""Her code host tools (`ashley.tools.code_host.CodeHostTools`) over the real adapters and fake forges, a person's
connections held in memory and, for the bench, the real Workshop: nothing is offered to a person who connected no host,
nor to another person of the household; the projects, a directory and a file read as the person's token reads them; a
file or a snapshot lands on the bench as her undoable file piece; what the host refuses or the arguments get wrong
comes back as an error saying why; a reading-only turn keeps the reads; no log line carries a token, path or text."""

import asyncio
import json

import httpx2
import pytest
from ashley import logs, services
from ashley.channels.limits import load as load_limits, smallest_result_chars
from ashley.codehost import config as codehost_config
from ashley.codehost.github import API, GitHubHost
from ashley.codehost.gitlab import GitLabHost
from ashley.codehost.host import CodeHost
from ashley.codehost.routed import RoutedCodeHost
from ashley.codehost.wire import Wire
from ashley.connections.connections import Connections
from ashley.connections.model import Kind
from ashley.db.pool import PoolDatabase
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.live import Live
from ashley.tools.code_host import CodeHostTools
from ashley.tools.reading import Reading
from ashley.workshop import rules as workshop_rules
from ashley.workshop.model import Owner
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.workshop import Workshop
from codehost_support import ESPHOME, TOKEN, FakeGitHub, FakeGitLab, Forge, repo_files
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, person, run
from live_support import FakeLive
from money_support import HeldConnections

CONFIG = codehost_config.load()
PATH = "owner/ashley"
YAML = "deploy/esphome/m5stack-atom-echo.yaml"
HOME, ALANA, SAM = 1, 7, 8
RESULT_CHARS = smallest_result_chars(load_limits())


def _wire(fake: Forge) -> Wire:
    return Wire(httpx2.AsyncClient(transport=fake.transport(), follow_redirects=False), 5)


def wire_hosts() -> tuple[FakeGitLab, FakeGitHub]:
    lab, hub = FakeGitLab({PATH: repo_files()}), FakeGitHub({PATH: repo_files()})
    services.register(CodeHost, RoutedCodeHost({"gitlab": GitLabHost(_wire(lab), CONFIG),
                                                "github": GitHubHost(_wire(hub), CONFIG)}))
    return lab, hub


def connected(*kinds: Kind) -> HeldConnections:
    held = HeldConnections()
    for kind in kinds:
        held.connect(HOME, "https://git.test" if kind == "gitlab" else API, TOKEN, kind, ALANA)
    services.register(Connections, held)
    return held


def say(tools: CodeHostTools | Reading, name: str, args: dict[str, object]) -> ToolResult:
    return asyncio.run(tools.call(ToolCall("c", name, args)))


def names(tools: CodeHostTools | Reading) -> list[str]:
    return [s.name for s in asyncio.run(tools.catalogue()).specs]


def read_all(tools: CodeHostTools, path: str, asked: str = "") -> str:
    """The file `path`, read page by page through `next_start` as she reads it."""
    text, start = "", 0
    while start is not None:
        page = json.loads(say(tools, "git_read_file", {"project": PATH, "path": asked or path, "start": start}).content)
        text, start = text + page["text"], page["next_start"]
    return text


def tools_for(person_id: int = ALANA, bench: int | None = None) -> CodeHostTools:
    return CodeHostTools(HOME, person_id, bench, CONFIG, RESULT_CHARS)


def test_a_person_who_connected_no_host_is_offered_nothing_and_so_is_another_of_the_household() -> None:
    wire_hosts()
    connected("gitlab")
    assert names(tools_for(SAM)) == []
    refused = say(tools_for(SAM), "git_projects", {})
    assert refused.is_error and refused.content.startswith("not_connected")
    assert names(tools_for(ALANA)) == ["git_projects", "git_tree", "git_read_file"]
    assert names(tools_for(ALANA, bench=3)) == ["git_projects", "git_tree", "git_read_file", "bench_add_from_git"]
    assert names(Reading(tools_for(ALANA, bench=3))) == ["git_projects", "git_tree", "git_read_file"]


def test_she_finds_the_project_lists_the_directory_and_reads_the_file_as_the_person_does() -> None:
    lab, _ = wire_hosts()
    connected("gitlab")
    tools = tools_for()
    projects = json.loads(say(tools, "git_projects", {}).content)
    assert [(p["host"], p["path"]) for p in projects["projects"]] == [("gitlab", PATH)]
    tree = json.loads(say(tools, "git_tree", {"project": PATH, "path": "deploy/esphome"}).content)
    assert [e["path"] for e in tree["entries"]] == [YAML, "deploy/esphome/wake-words"]
    assert read_all(tools, YAML, "/" + YAML) == ESPHOME.read_text()
    assert {c for _, _, _, c in lab.seen} == {TOKEN}


def test_a_file_longer_than_any_cap_is_read_in_pages_each_whole_to_the_loop_and_a_word_past_the_first_is_found() -> None:
    lab, _ = wire_hosts()
    body = ("a line with \"quotes\"\n" * 3000) + "the word herdr is here\n" + ("tail\n" * 40)
    assert CONFIG.read_bytes > len(body) > 4 * RESULT_CHARS
    lab.projects[PATH]["long.md"] = body.encode()
    connected("gitlab")
    tools, start, found, pages = tools_for(), 0, False, 0
    while start is not None:
        got = say(tools, "git_read_file", {"project": PATH, "path": "long.md", "start": start})
        assert not got.is_error and len(got.content) <= RESULT_CHARS
        page = json.loads(got.content)
        assert page["total_chars"] == len(body) and page["start"] == start and page["truncated"] is False
        found, pages, start = found or "herdr" in page["text"], pages + 1, page["next_start"]
    assert found and pages > 1


def test_start_past_the_end_or_not_a_count_is_refused() -> None:
    wire_hosts()
    connected("gitlab")
    for start in (10**9, -1, "3", True):
        got = say(tools_for(), "git_read_file", {"project": PATH, "path": YAML, "start": start})
        assert got.is_error and got.content.startswith("bad_arguments")


def test_a_binary_file_is_refused() -> None:
    lab, _ = wire_hosts()
    lab.projects[PATH]["logo.bin"] = b"\xff\xfe\x00"
    connected("gitlab")
    binary = say(tools_for(), "git_read_file", {"project": PATH, "path": "logo.bin"})
    assert binary.is_error and binary.content.startswith("binary")


def test_with_two_hosts_she_names_which_and_lists_both() -> None:
    wire_hosts()
    connected("gitlab", "github")
    tools = tools_for()
    spec = {s.name: s for s in asyncio.run(tools.catalogue()).specs}["git_read_file"]
    assert spec.parameters["required"] == ["host", "project", "path"]
    both = json.loads(say(tools, "git_projects", {}).content)["projects"]
    assert sorted(p["host"] for p in both) == ["github", "gitlab"]
    assert say(tools, "git_tree", {"project": PATH}).is_error
    on_github = json.loads(say(tools, "git_tree", {"host": "github", "project": PATH}).content)
    assert [e["path"] for e in on_github["entries"]] == ["README.md", "deploy"]


def test_what_the_arguments_and_the_host_get_wrong_is_an_error_that_says_why() -> None:
    lab, _ = wire_hosts()
    connected("gitlab")
    tools = tools_for()
    bad: list[tuple[str, dict[str, object]]] = [("git_read_file", {"project": PATH, "path": "../etc/passwd"}),
                       ("git_read_file", {"project": PATH}),
                       ("git_tree", {"project": PATH, "ref": "a..b"}),
                       ("git_tree", {"project": ""}),
                       ("git_tree", {"project": PATH, "bogus": 1}),
                       ("git_tree", {"project": PATH, "host": "github"}),
                       ("bench_add_from_git", {"project": PATH})]
    for name, args in bad:
        got = say(tools, name, args)
        assert got.is_error and got.content.startswith(("bad_arguments", "unknown_tool")), (name, args, got.content)
    assert say(tools, "git_tree", {"project": "nobody/nothing"}).content.startswith("not_found")
    lab.token = "rotated"
    assert say(tools, "git_projects", {}).content.startswith("refused")
    lab.token, lab.down = TOKEN, 503
    assert say(tools, "git_projects", {}).content.startswith("unreachable")


def test_a_file_and_a_snapshot_land_on_the_bench_as_her_undoable_file_pieces(db_url: str) -> None:
    home = household(db_url)
    alana = Owner(home, person(db_url, home))
    wire_hosts()
    held = HeldConnections()
    held.connect(home, "https://git.test", TOKEN, "gitlab", alana.person_id)
    services.register(Connections, held)

    async def scenario() -> None:
        database = PoolDatabase(db_url)
        await database.open()
        services.register(Live, FakeLive())
        services.register(Workshop, PostgresWorkshop(database, workshop_rules.load()))
        services.register(ObjectStore, MemoryStore())
        try:
            shop = services.get(Workshop)
            bench = await shop.open(alana, "shed")
            tools = CodeHostTools(home, alana.person_id, bench.id, CONFIG, RESULT_CHARS)
            one = json.loads((await tools.call(ToolCall("c", "bench_add_from_git",
                                                        {"project": PATH, "path": YAML}))).content)
            snap = json.loads((await tools.call(ToolCall("c", "bench_add_from_git", {"project": PATH}))).content)
            assert one["size"] == len(ESPHOME.read_bytes()) and snap["media_type"] == "application/zip"
            pieces = (await shop.read(alana, bench.id)).pieces
            assert [(p.kind, p.text.title) for p in pieces] == [("file", "m5stack-atom-echo.yaml"),
                                                                 ("file", "owner-ashley-default.zip")]
            log = await shop.log(alana, bench.id)
            assert {row.by.author for row in log} == {"ashley"}
        finally:
            await database.close()

    run(scenario())


def test_no_log_line_carries_a_token_a_path_or_text(capsys: pytest.CaptureFixture[str]) -> None:
    wire_hosts()
    connected("gitlab")
    logs.setup()
    capsys.readouterr()
    calls: list[tuple[str, dict[str, object]]] = [("git_projects", {}), ("git_tree", {"project": PATH, "path": "deploy"}),
                                                  ("git_read_file", {"project": PATH, "path": YAML})]
    for name, args in calls:
        say(tools_for(), name, args)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    assert sum("event=tools.call" in ln for ln in lines) == 3 and sum("event=codehost.get" in ln for ln in lines) == 3
    assert not any(TOKEN in ln or "m5stack" in ln or "esphome" in ln or "git.test" in ln for ln in lines)
