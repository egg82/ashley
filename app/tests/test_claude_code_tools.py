"""Her Claude Code tools (`ashley.tools.claude_code.ClaudeCodeTools`) over the real `HttpBridge` and the real bridge
program on real mutual TLS, with the fake `herdr` behind it that replays answers captured from the real CLI, and a
person's connections held in memory: nothing is offered to a person who connected no bridge, nor to another person of
the household, nor where the reply does not reach the speaker alone; the sessions list, a screen reads, a prompt, a
start and a close reach herdr as the bridge sends them; each reason the bridge refuses with comes back as an error
saying what to do; no log line carries a prompt, a screen, a path or the token."""

import asyncio
import json
from datetime import UTC, datetime
from collections.abc import Generator
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from ashley import logs, services
from ashley.channels.limits import load as load_limits, smallest_result_chars
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.herdr.bridge import Bridge
from ashley.herdr.config import load
from ashley.herdr.http_bridge import HttpBridge
from ashley.watches.config import CONFIG as WATCHES
from ashley.watches.watches import Watches
from ashley.herdr.transport import ClientCertificate
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import claude_code, claude_code_config
from ashley.tools.claude_code import ClaudeCodeTools
from ashley.tools.reading import Reading
from herdr_bridge.runner import HerdrTimeout, Outcome

from watch_session_support import DownWatches, MemoryWatches
from herdr_bridge_support import PERSON, THROWAWAY, TOKEN, FakeHerdr, ca_with_client, captured, listing, ok, \
    serving, session_ids
from money_support import HeldConnections

CONFIG = claude_code_config.load()
RESULT_CHARS = smallest_result_chars(load_limits())
HOME, ALANA, SAM = 1, int(PERSON), 8
PANE = "w5H:pK"
WORKING = session_ids()[0]
ALL = ["claude_sessions", "claude_read", "claude_prompt", "claude_start", "claude_close"]
Replies = dict[tuple[str, ...], Outcome | Exception | list[Outcome]]


@dataclass
class World:
    port: int
    pin: str
    calls: list[tuple[str, ...]]
    project: Path

    def connect(self, person: int = ALANA) -> HeldConnections:
        held = HeldConnections()
        held.connect(HOME, f"https://127.0.0.1:{self.port}#sha256={self.pin}", TOKEN, "herdr", person)
        services.register(Connections, held)
        return held


def replies(project: Path, prompt: str) -> Replies:
    return {
        ("agent", "list"): listing(), ("tab", "list"): ok("tab_list.json"), ("--version",): ok("version.out"),
        ("agent", "read", PANE, "--source", "recent-unwrapped", "--lines", "80"): ok("agent_read.txt"),
        ("agent", "prompt", PANE, prompt): ok("agent_prompt.json"), ("pane", "close", PANE): ok("pane_close.json"),
        ("tab", "create", "--cwd", str(project), "--label", "bridge-capture", "--no-focus"): ok("tab_create.json"),
        ("agent", "start", "bridge-capture", "--kind", "claude", "--pane", PANE, "--timeout", "5000"):
            ok("agent_start.json")}


def serve(tmp_path: Path, changes: Replies) -> Generator[World]:
    project = tmp_path / "project"
    project.mkdir()
    ca, client = ca_with_client(tmp_path, "app")
    services.register(Bridge, HttpBridge(ClientCertificate(str(client.cert), str(client.key)),
                                         replace(load(), timeout_s=5.0)))
    table = {**replies(project, "clone it and look"), **changes}
    with serving(tmp_path, ca, FakeHerdr(table), roots=(str(tmp_path),)) as served:
        yield World(served.port, served.pin, served.bridge.runner.calls, project)


@pytest.fixture
def world(tmp_path: Path) -> Generator[World]:
    yield from serve(tmp_path, {})


@pytest.fixture
def starting(tmp_path: Path) -> Generator[World]:
    """A bridge whose herdr lists the new session only once it is started."""
    yield from serve(tmp_path, {("agent", "list"): [listing(drop=(THROWAWAY,)), listing()]})


@pytest.fixture
def silent(tmp_path: Path) -> Generator[World]:
    """A bridge whose herdr never answers a prompt or a close."""
    yield from serve(tmp_path, {("agent", "prompt", PANE, "clone it and look"): HerdrTimeout(),
                                ("pane", "close", PANE): HerdrTimeout()})


def tools_for(person: int = ALANA) -> ClaudeCodeTools:
    return ClaudeCodeTools(HOME, person, CONFIG, RESULT_CHARS)


def say(tools: ClaudeCodeTools | Reading, name: str, args: dict[str, object]) -> ToolResult:
    return asyncio.run(asyncio.wait_for(tools.call(ToolCall("c", name, args)), 30))


def names(tools: ClaudeCodeTools | Reading) -> list[str]:
    return [s.name for s in asyncio.run(tools.catalogue()).specs]


def error(got: ToolResult, outcome: str) -> None:
    assert got.is_error and got.content.startswith(outcome + ":"), got.content


def test_a_person_without_a_bridge_is_offered_nothing_and_so_is_another_of_the_household(world: World) -> None:
    world.connect()
    assert names(tools_for(SAM)) == []
    error(say(tools_for(SAM), "claude_sessions", {}), "not_connected")
    assert names(tools_for(ALANA)) == ALL
    assert names(Reading(tools_for(ALANA))) == ["claude_sessions", "claude_read"]
    assert world.calls == []


def test_the_instructions_are_offered_with_the_tools_and_not_without_them(world: World) -> None:
    world.connect()
    offered = asyncio.run(tools_for(ALANA).catalogue())
    assert offered.instructions and "claude_sessions" in offered.instructions
    assert asyncio.run(tools_for(SAM).catalogue()).instructions is None


def test_no_connection_at_all_offers_nothing() -> None:
    services.register(Connections, HeldConnections())
    assert names(tools_for()) == []


INBOUND = Inbound(household_id=HOME, thread="person:7:web", text="hi", kind="chat", medium="text", audience="owner",
                  speaker_id=ALANA, shared=False, place=None, channel="web", later=True, later_by="turn")


def test_the_source_is_offered_only_where_the_reply_reaches_the_speaker_alone() -> None:
    services.register(Connections, HeldConnections())
    assert "claude_code" in sources(INBOUND)
    assert "claude_code" not in sources(replace(INBOUND, audience="household", shared=True))
    assert "claude_code" not in sources(replace(INBOUND, device_id=3))
    assert "claude_code" not in sources(replace(INBOUND, speaker_id=None))


def test_she_lists_the_sessions_and_reads_one_as_the_bridge_serves_them(world: World) -> None:
    world.connect()
    listed = json.loads(say(tools_for(), "claude_sessions", {}).content)["sessions"]
    assert [s["label"] for s in listed][:3] == ["app-2", "bridge-capture", "notes"]
    assert {s["id"]: s["status"] for s in listed}[WORKING] == "working"
    read = json.loads(say(tools_for(), "claude_read", {"session": THROWAWAY}).content)
    assert read["text"] == captured("agent_read.txt") and read["truncated"] is False


def test_the_listing_names_the_roots_and_a_refused_start_points_at_them(world: World, tmp_path: Path) -> None:
    world.connect()
    assert json.loads(say(tools_for(), "claude_sessions", {}).content)["roots"] == [str(tmp_path.resolve())]
    refused = say(tools_for(), "claude_start", {"dir": "/etc", "label": "bridge-capture"})
    error(refused, "dir_not_allowed")
    assert "roots" in refused.content and "claude_sessions" in refused.content
    assert "roots" in next(s.description for s in claude_code.specs(CONFIG) if s.name == "claude_sessions")


def test_a_prompt_to_a_ready_session_reaches_herdr_and_a_working_one_is_refused_unsent(world: World) -> None:
    world.connect()
    sent = say(tools_for(), "claude_prompt", {"session": THROWAWAY, "text": "clone it and look"})
    assert json.loads(sent.content) == {"sent": True, "watched": False}   # no store wired: she is told it is not watched
    assert ("agent", "prompt", PANE, "clone it and look") in world.calls
    before = len(world.calls)
    busy = say(tools_for(), "claude_prompt", {"session": WORKING, "text": "x"})
    error(busy, "busy")
    assert "claude_read" in busy.content and not any(c[:2] == ("agent", "prompt") for c in world.calls[before:])


def test_she_starts_a_session_under_the_root_and_closes_it(starting: World) -> None:
    world = starting
    world.connect()
    made = say(tools_for(), "claude_start", {"dir": str(world.project), "label": "bridge-capture"})
    assert json.loads(made.content)["id"] == THROWAWAY
    closed = say(tools_for(), "claude_close", {"session": THROWAWAY})
    assert json.loads(closed.content) == {"closed": True} and ("pane", "close", PANE) in world.calls
    error(say(tools_for(), "claude_start", {"dir": "/etc", "label": "bridge-capture"}), "dir_not_allowed")


def test_a_read_is_cut_to_the_end_she_is_shown(world: World) -> None:
    world.connect()
    text = captured("agent_read.txt")
    result = asyncio.run(ClaudeCodeTools(HOME, ALANA, CONFIG, 120).call(ToolCall("c", "claude_read", {"session": THROWAWAY})))
    got = json.loads(result.content)
    assert len(result.content) <= 120 and got["text"] == text[len(text) - len(got["text"]):]
    assert 0 < len(got["text"]) < len(text) and got["truncated"] is True


def test_what_the_arguments_and_the_bridge_get_wrong_is_an_error_that_says_what_to_do(world: World) -> None:
    world.connect()
    bad: list[tuple[str, dict[str, object]]] = [
        ("claude_read", {}), ("claude_read", {"session": THROWAWAY, "lines": 0}),
        ("claude_read", {"session": THROWAWAY, "lines": CONFIG.read_lines_max + 1}),
        ("claude_prompt", {"session": THROWAWAY, "text": "x" * (CONFIG.prompt_chars + 1)}),
        ("claude_prompt", {"session": THROWAWAY}), ("claude_close", {"session": THROWAWAY, "bogus": 1}),
        ("claude_start", {"dir": "/tmp"}), ("claude_nothing", {})]
    for name, args in bad:
        got = say(tools_for(), name, args)
        assert got.is_error and got.content.startswith(("bad_arguments", "unknown_tool")), (name, args, got.content)
    error(say(tools_for(), "claude_read", {"session": "00000000-0000-0000-0000-000000000000"}), "not_found")
    assert not any(c[:2] == ("agent", "prompt") for c in world.calls)


def test_a_bridge_that_is_down_or_not_the_one_pinned_is_refused_with_the_reason(world: World) -> None:
    held = world.connect()
    held.connect(HOME, f"https://127.0.0.1:{world.port}#sha256={'0' * 64}", TOKEN, "herdr", ALANA)
    error(say(tools_for(), "claude_sessions", {}), "pin_mismatch")
    held.connect(HOME, "https://127.0.0.1:9#sha256=" + "0" * 64, TOKEN, "herdr", ALANA)
    error(say(tools_for(), "claude_sessions", {}), "herdr_unavailable")
    held.down = True
    error(say(tools_for(), "claude_sessions", {}), "unavailable")
    with pytest.raises(Exception):
        asyncio.run(tools_for().catalogue())


def test_a_change_that_got_no_answer_says_it_may_have_happened(silent: World) -> None:
    silent.connect()
    changes: list[tuple[str, dict[str, object]]] = [
        ("claude_prompt", {"session": THROWAWAY, "text": "clone it and look"}), ("claude_close", {"session": THROWAWAY})]
    for name, args in changes:
        got = say(tools_for(), name, args)
        error(got, "unconfirmed")
        assert "claude_sessions" in got.content


def test_no_log_line_carries_a_prompt_a_screen_a_path_or_the_token(starting: World,
                                                                    capsys: pytest.CaptureFixture[str]) -> None:
    world = starting
    world.connect()
    logs.setup()
    capsys.readouterr()
    say(tools_for(), "claude_start", {"dir": str(world.project), "label": "bridge-capture"})
    say(tools_for(), "claude_prompt", {"session": THROWAWAY, "text": "clone it and look"})
    say(tools_for(), "claude_read", {"session": THROWAWAY})
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("ts=")]
    assert sum("event=tools.call" in ln and "outcome=ok" in ln for ln in lines) == 3
    for secret in ("clone it and look", captured("agent_read.txt")[:30], str(world.project), TOKEN):
        assert not any(secret in ln for ln in lines)


def watched_with(*, bench: int | None = None) -> tuple[MemoryWatches, ClaudeCodeTools]:
    held = MemoryWatches()
    services.register(Watches, held)
    return held, ClaudeCodeTools(HOME, ALANA, CONFIG, RESULT_CHARS, bench)


def test_a_session_she_starts_is_watched_from_the_state_it_reports_and_the_bench_that_started_it(starting: World) -> None:
    starting.connect()
    held, tools = watched_with(bench=6)
    made = json.loads(say(tools, "claude_start", {"dir": str(starting.project), "label": "bridge-capture"}).content)
    assert made["watched"] is True
    [arm] = held.armed
    assert (arm.household_id, arm.person_id, arm.kind, arm.target, arm.bench_id) == (HOME, ALANA, "claude_session", THROWAWAY, 6)
    assert arm.armed_by == "handoff" and arm.label == "bridge-capture" and arm.tools is None
    assert arm.baseline == {THROWAWAY: {"status": made["status"], "seq": 1631}}


def test_a_hand_off_watch_takes_the_kinds_defaults(starting: World) -> None:
    starting.connect()
    held, tools = watched_with()
    before = datetime.now(UTC)
    say(tools, "claude_start", {"dir": str(starting.project), "label": "bridge-capture"})
    [arm] = held.armed
    kind = WATCHES.kinds["claude_session"]
    assert (arm.track, arm.when, arm.until, arm.interval_s) == (kind.track, kind.when, kind.handoff_until, kind.interval_s)
    assert abs((arm.expires_at - before).total_seconds() - kind.handoff_hours * 3600) < 60


def test_a_prompt_watches_the_session_from_the_state_it_was_in_before_the_prompt_went(world: World) -> None:
    world.connect()
    held, tools = watched_with()
    sent = json.loads(say(tools, "claude_prompt", {"session": THROWAWAY, "text": "clone it and look"}).content)
    assert sent == {"sent": True, "watched": True}
    assert world.calls.index(("agent", "list")) < world.calls.index(("agent", "prompt", PANE, "clone it and look"))
    [arm] = held.armed
    assert (arm.target, arm.bench_id, arm.baseline) == (THROWAWAY, None, {THROWAWAY: {"status": "done", "seq": 1631}})


def test_a_prompt_that_is_refused_or_a_store_that_is_down_watches_nothing_new(world: World) -> None:
    world.connect()
    held, tools = watched_with()
    error(say(tools, "claude_prompt", {"session": WORKING, "text": "x"}), "busy")
    assert held.armed == []
    services.register(Watches, DownWatches())
    got = json.loads(say(tools, "claude_prompt", {"session": THROWAWAY, "text": "clone it and look"}).content)
    assert got == {"sent": True, "watched": False}
