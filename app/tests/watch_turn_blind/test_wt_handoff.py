"""`claude_start` and `claude_prompt` arm through `Watches.arm` with `armed_by` `handoff`, the kind's `handoff_until`
(`[[gone]]`) and `handoff_hours` (72), and the session's state before the prompt as the baseline; their result still says
`watched`. Over a fake Bridge and a recording store, with no database."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ashley import services
from ashley.channels.limits import load as load_limits, smallest_result_chars
from ashley.connections.connections import Connections
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Access, BridgeFailed, OutFile, Screen, Session, SessionList, Status, Whoami
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools import claude_code_config
from ashley.tools.claude_code import ClaudeCodeTools
from ashley.watches.watches import Arm, Armed, Watch, Watches, WatchesUnavailable
from money_support import HeldConnections
from watch_turn_blind_support import KIND, LABEL, SESSION, arm_fields, is_gone_only, items_of

HOME, ALANA, BENCH = 1, 7, 6
CONFIG = claude_code_config.load()
RESULT_CHARS = smallest_result_chars(load_limits())


@dataclass
class RecordingWatches(Watches):
    arms: list[Arm] = field(default_factory=list[Arm])
    down: bool = False

    async def arm(self, arm: Arm) -> Armed:
        if self.down:
            raise WatchesUnavailable("down")
        self.arms.append(arm)
        return Armed(len(self.arms), True)

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        raise AssertionError("not used")

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        raise AssertionError("not used")

    async def get(self, watch_id: int) -> Watch | None:
        raise AssertionError("not used")

    async def due(self, limit: int) -> tuple[Watch, ...]:
        raise AssertionError("not used")

    async def record(self, watch_id: int, version: int, check: Any) -> bool:
        raise AssertionError("not used")

    async def expire(self, keep_s: float) -> Any:
        raise AssertionError("not used")


@dataclass
class FakeBridge(Bridge):
    """Lists SESSION in `status`/`seq`; a prompt moves it to `after`; `refuse` makes a prompt fail."""

    status: Status = "done"
    seq: int = 1631
    after: tuple[Status, int] = ("working", 1632)
    listed: bool = True
    refuse: bool = False

    def session(self, label: str = "bridge-capture") -> Session:
        return Session(SESSION, label, "/d", self.status, self.seq, None)

    async def sessions(self, access: Access) -> SessionList:
        return SessionList((self.session(),) if self.listed else (), None, ("/d",))

    async def whoami(self, access: Access) -> Whoami:
        raise AssertionError("not used")

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        return Screen("the end of the screen", False, 1)

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        if self.refuse:
            raise BridgeFailed("busy")
        self.status, self.seq = self.after

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        self.status, self.seq = "working", 5
        return self.session(label)

    async def close(self, access: Access, session_id: str) -> None:
        raise AssertionError("not used")

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        raise AssertionError("not used")

    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        raise AssertionError("not used")

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        raise AssertionError("not used")


def rig(bench: int | None = BENCH, bridge: FakeBridge | None = None) -> tuple[RecordingWatches, FakeBridge, ClaudeCodeTools]:
    held = HeldConnections()
    held.connect(HOME, "https://127.0.0.1:7843#sha256=" + "0" * 64, "token", "herdr", ALANA)
    watches, fake = RecordingWatches(), bridge or FakeBridge()
    services.register(Connections, held)
    services.register(Bridge, fake)
    services.register(Watches, watches)
    return watches, fake, ClaudeCodeTools(HOME, ALANA, CONFIG, RESULT_CHARS, bench)


def say(tools: ClaudeCodeTools, name: str, args: dict[str, object]) -> ToolResult:
    return asyncio.run(asyncio.wait_for(tools.call(ToolCall("c", name, args)), 30))


def body(got: ToolResult) -> dict[str, Any]:
    assert not got.is_error, got.content
    return json.loads(got.content)


def test_a_prompt_arms_a_hand_off_watch_from_the_state_the_session_was_in_before_it() -> None:
    watches, _, tools = rig()
    assert body(say(tools, "claude_prompt", {"session": SESSION, "text": "go"})) == {"sent": True, "watched": True}
    [arm] = watches.arms
    got = arm_fields(arm)
    assert (got["kind"], got["target"], got["armed_by"], got["bench_id"]) == (KIND, SESSION, "handoff", BENCH)
    assert got["household_id"] == HOME and got["person_id"] == ALANA and got["label"] == "bridge-capture"
    assert got["baseline"] == items_of("done", 1631)


def test_a_start_arms_a_hand_off_watch_from_the_state_it_reports() -> None:
    watches, _, tools = rig(bench=None)
    made = body(say(tools, "claude_start", {"dir": "/d", "label": LABEL[:20]}))
    assert made["watched"] is True
    [arm] = watches.arms
    got = arm_fields(arm)
    assert (got["armed_by"], got["bench_id"], got["target"]) == ("handoff", None, SESSION)
    assert got["baseline"] == items_of("working", 5)


def test_a_hand_off_watch_ends_when_the_session_closes_and_lasts_the_kinds_hand_off_hours() -> None:
    watches, _, tools = rig()
    before = datetime.now(UTC)
    say(tools, "claude_prompt", {"session": SESSION, "text": "go"})
    [arm] = watches.arms
    assert is_gone_only(arm_fields(arm)["until"])
    lasts = arm_fields(arm)["expires_at"]
    assert isinstance(lasts, datetime)
    assert timedelta(hours=71.9) < lasts - before < timedelta(hours=72.1)


def test_each_later_hand_off_arms_again_from_the_state_it_found() -> None:
    watches, bridge, tools = rig()
    say(tools, "claude_prompt", {"session": SESSION, "text": "one"})
    bridge.status, bridge.seq = "done", 1640
    say(tools, "claude_prompt", {"session": SESSION, "text": "two"})
    assert [arm_fields(a)["baseline"] for a in watches.arms] == [items_of("done", 1631), items_of("done", 1640)]


def test_the_baseline_is_the_state_before_the_prompt_and_not_the_one_it_caused() -> None:
    watches, bridge, tools = rig()
    say(tools, "claude_prompt", {"session": SESSION, "text": "go"})
    assert (bridge.status, bridge.seq) == bridge.after
    assert arm_fields(watches.arms[0])["baseline"] != items_of(*bridge.after)


def test_a_store_that_is_down_still_sends_the_prompt_and_says_it_is_not_watched() -> None:
    watches, bridge, tools = rig()
    watches.down = True
    assert body(say(tools, "claude_prompt", {"session": SESSION, "text": "go"})) == {"sent": True, "watched": False}
    assert (bridge.status, bridge.seq) == bridge.after


def test_an_unwired_store_says_the_same_and_does_not_fail_the_start() -> None:
    _, _, tools = rig()
    services.unregister(Watches)
    assert body(say(tools, "claude_prompt", {"session": SESSION, "text": "go"}))["watched"] is False
    assert body(say(tools, "claude_start", {"dir": "/d", "label": "x"}))["watched"] is False


def test_a_prompt_that_is_refused_arms_nothing() -> None:
    watches, bridge, tools = rig()
    bridge.refuse = True
    got = say(tools, "claude_prompt", {"session": SESSION, "text": "go"})
    assert got.is_error and watches.arms == []


def test_a_session_the_bridge_does_not_list_is_prompted_and_not_watched() -> None:
    watches, bridge, tools = rig()
    bridge.listed = False
    assert body(say(tools, "claude_prompt", {"session": SESSION, "text": "go"}))["watched"] is False
    assert watches.arms == []


@pytest.mark.parametrize("name,args", [("claude_sessions", {}), ("claude_read", {"session": SESSION})])
def test_looking_at_a_session_arms_nothing(name: str, args: dict[str, object]) -> None:
    watches, _, tools = rig()
    say(tools, name, args)
    assert watches.arms == []
