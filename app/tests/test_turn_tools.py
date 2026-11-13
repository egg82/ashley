"""The tools one turn offers (`channels.turn_tools.for_turn`): the household's everyday tools alone on a turn whose
fields call for nothing; on a bench's talk, that bench's tools after it; on the person's own web chat, opening a bench;
nothing added without a known speaker. A source the shared catalogue could not reach is still named when a turn adds its own.
And `open_bench` opens a bench for the speaker, returning its id and the room's path."""

import asyncio
import json
from dataclasses import dataclass, field, replace
from typing import Any
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.channels.model import Inbound
from ashley.connections.connections import Connections
from ashley.channels.turn_tools import for_turn, sources
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.tools.composite import CompositeTools
from ashley.tools.everyday import HouseholdTools
from ashley.tools.open_bench import OpenBenchTools
from ashley.tools.tools import Catalogue, Tools, ToolsUnavailable
from ashley.workshop.commands import Command
from ashley.workshop.model import Bench, Owner
from ashley.workshop.reactions import Unseen
from ashley.workshop.workshop import Applied, BenchView, Logged, Placed, UnknownOwner, Workshop, WorkshopUnavailable
from money_support import HeldConnections

EPOCH = datetime(2026, 10, 29, tzinfo=UTC)
WEB = Inbound(household_id=10, thread="person:1:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=1, shared=False, place=None, channel="web", later=True, later_by="turn", opens_benches=True)
BENCH = replace(WEB, thread="bench:4", kind="brainstorm", opens_benches=False, bench_id=4)
VOICE = Inbound(household_id=10, thread="device:7", text="hi", kind="command", medium="spoken", audience="present",
                speaker_id=None, shared=True, place="kitchen", channel="voice")


class Fixed(Tools):
    def __init__(self, names: tuple[str, ...], unreachable: tuple[str, ...] = (), down: bool = False) -> None:
        self.names, self.unreachable, self.down = names, unreachable, down
        self.called: list[str] = []

    async def catalogue(self) -> Catalogue:
        if self.down:
            raise ToolsUnavailable("down")
        return Catalogue(tuple(ToolSpec(n, n, {"type": "object"}) for n in self.names), None, self.unreachable)

    async def call(self, call: ToolCall) -> ToolResult:
        self.called.append(call.name)
        return ToolResult(call.id, "done")


@dataclass
class Opening(Workshop):
    raises: Exception | None = None
    opened: list[tuple[Owner, str]] = field(default_factory=list[tuple[Owner, str]])

    async def open(self, owner: Owner, title: str) -> Bench:
        if self.raises is not None:
            raise self.raises
        if not title.strip():
            raise ValueError("empty")
        self.opened.append((owner, title))
        return Bench(12, owner.household_id, owner.person_id, title, EPOCH, None)

    async def of_kind(self, household_id: int, kind: str) -> tuple[Placed, ...]:
        raise NotImplementedError

    async def open_benches(self, owner: Owner) -> list[Bench]:
        raise NotImplementedError

    async def close(self, owner: Owner, bench_id: int) -> Bench:
        raise NotImplementedError

    async def closed_benches(self, owner: Owner) -> list[Bench]:
        raise NotImplementedError

    async def reopen(self, owner: Owner, bench_id: int) -> Bench:
        raise NotImplementedError

    async def read(self, owner: Owner, bench_id: int) -> BenchView:
        raise NotImplementedError

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        raise NotImplementedError

    async def undo_turn(self, owner: Owner, bench_id: int, by: Any, seq: int) -> Any:
        raise NotImplementedError

    async def log(self, owner: Owner, bench_id: int) -> list[Logged]:
        raise NotImplementedError

    async def unseen(self, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
        raise NotImplementedError

    async def reaction_ages(self, bench_id: int, window_s: float) -> tuple[float, ...]:
        raise NotImplementedError

    async def reacted(self, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
        raise NotImplementedError


@pytest.fixture
def everyday() -> Fixed:
    tools = Fixed(("HassTurnOn", "look_up"))
    services.register(Tools, tools)
    return tools


def names(tools: Tools) -> list[str]:
    return [s.name for s in asyncio.run(tools.catalogue()).specs]


@pytest.mark.parametrize("inbound", [VOICE, replace(BENCH, speaker_id=None), replace(WEB, speaker_id=None)])
def test_a_turn_whose_fields_call_for_nothing_gets_its_households_everyday_tools_alone(everyday: Fixed,
                                                                                     inbound: Inbound) -> None:
    got = for_turn(inbound)
    assert isinstance(got, HouseholdTools) and names(got) == list(everyday.names)


def test_a_turn_whose_channel_names_the_speaker_adds_only_reminders_the_households_devices_screens_and_house_changes(everyday: Fixed) -> None:
    assert set(sources(replace(WEB, opens_benches=False))) == {"reminders", "devices", "house_change", "screen"}


def test_a_device_s_own_thread_offers_its_screen_whoever_speaks_and_a_voice_turn_with_no_device_none(everyday: Fixed) -> None:
    assert set(sources(replace(VOICE, speaker_id=None, device_id=7))) == {"screen"}
    assert set(sources(replace(VOICE, speaker_id=None, device_id=None))) == set()


def test_a_bench_turn_offers_the_shared_tools_then_that_benchs(everyday: Fixed) -> None:
    got = names(for_turn(BENCH))
    assert got[:2] == ["HassTurnOn", "look_up"] and "bench_edit" in got and "open_bench" not in got


def test_her_web_chat_offers_opening_a_bench_the_households_devices_and_no_bench_tools(everyday: Fixed) -> None:
    assert names(for_turn(WEB)) == ["HassTurnOn", "look_up", "open_bench", "household_devices", "send_readers"]


def test_the_speakers_code_host_is_a_source_only_where_connections_open_and_the_reply_reaches_them_alone(
        everyday: Fixed) -> None:
    assert "code_host" not in sources(WEB)
    services.register(Connections, HeldConnections())
    assert "code_host" in sources(WEB) and "code_host" in sources(BENCH)
    assert "code_host" not in sources(replace(WEB, audience="household", shared=True))


def test_a_call_to_a_shared_tool_on_a_bench_turn_still_reaches_the_shared_tools(everyday: Fixed) -> None:
    tools = for_turn(BENCH)
    asyncio.run(tools.catalogue())
    asyncio.run(tools.call(ToolCall("c", "HassTurnOn", {})))
    assert everyday.called == ["HassTurnOn"]


def test_what_the_shared_tools_could_not_reach_is_still_named_on_a_turn_that_adds_its_own() -> None:
    services.register(Tools, CompositeTools({"house": Fixed((), down=True), "search": Fixed(("look_up",))}))
    assert "house" in asyncio.run(for_turn(WEB).catalogue()).unreachable
    services.register(Tools, Fixed((), down=True))
    assert "everyday" in asyncio.run(for_turn(WEB).catalogue()).unreachable


def test_open_bench_opens_one_for_the_speaker_and_returns_its_id_and_path() -> None:
    shop = Opening()
    services.register(Workshop, shop)
    got = asyncio.run(OpenBenchTools(10, 1).call(ToolCall("c", "open_bench", {"title": "Shed plans"})))
    assert not got.is_error and json.loads(got.content) == {"bench_id": 12, "path": "/workshop/12"}
    assert shop.opened == [(Owner(10, 1), "Shed plans")]


@pytest.mark.parametrize(("args", "raises", "outcome"), [
    ({"title": 5}, None, "bad_arguments"), ({"title": "t", "person_id": 3}, None, "bad_arguments"),
    ({"title": " "}, None, "bad_title"),
    ({"title": "t"}, WorkshopUnavailable(), "unavailable"), ({"title": "t"}, UnknownOwner(), "unavailable")])
def test_open_bench_that_cannot_open_is_an_error_naming_why(args: dict[str, object], raises: Exception | None,
                                                            outcome: str) -> None:
    services.register(Workshop, Opening(raises))
    got = asyncio.run(OpenBenchTools(10, 1).call(ToolCall("c", "open_bench", args)))
    assert got.is_error and got.content.startswith(outcome + ":")
