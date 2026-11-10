"""Her moving the person's page: `move_page` is offered only on a thread whose channel is the speaker's own page (web
chat, a bench's talk); a move publishes `PageMoved` to that person's screens alone, never another person's or a
device's; a bench must be one of the speaker's open benches, else nothing moves; the wire carries ids only."""

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import pytest
from ashley import services
from ashley.api.live import wire
from ashley.api.live_models import LivePage
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import for_turn
from ashley.inference.model import ToolCall, ToolResult, ToolSpec
from ashley.live.events import DeviceViewer, PageMoved, PageRoom, Shown, Viewer, decode, encode, shown_to
from ashley.live.live import Live
from ashley.tools.move_page import MovePageTools
from ashley.tools.tools import Catalogue, Tools
from ashley.workshop.commands import Command
from ashley.workshop.model import Bench, Owner
from ashley.workshop.reactions import Unseen
from ashley.workshop.workshop import Applied, BenchView, Logged, Placed, Workshop, WorkshopUnavailable
from live_support import FakeLive

EPOCH = datetime(2026, 10, 29, tzinfo=UTC)
WEB = Inbound(household_id=10, thread="person:1:web", text="hi", kind="chat", medium="text", audience="owner",
              speaker_id=1, shared=False, place=None, channel="web", later=True, later_by="turn", opens_benches=True,
              on_page=True)
BENCH_TALK = replace(WEB, thread="bench:4", kind="brainstorm", opens_benches=False, bench_id=4)
DM = Inbound(household_id=10, thread="discord:dm:1", text="hi", kind="chat", medium="text", audience="owner",
             speaker_id=1, shared=False, place=None, channel="discord")
VOICE = Inbound(household_id=10, thread="device:7", text="hi", kind="command", medium="spoken", audience="present",
                speaker_id=None, shared=True, place="kitchen", channel="voice")


class Everyday(Tools):
    async def catalogue(self) -> Catalogue:
        return Catalogue((ToolSpec("HassTurnOn", "on", {"type": "object"}),), None)

    async def call(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, "done")


@dataclass
class Benches(Workshop):
    """Answers `open_benches` with `mine`, the asking owner's open benches; nothing else is asked."""

    mine: tuple[int, ...] = (4, 6)
    down: bool = False
    asked: list[Owner] = field(default_factory=list[Owner])

    async def of_kind(self, household_id: int, kind: str) -> tuple[Placed, ...]:
        raise NotImplementedError

    async def open_benches(self, owner: Owner) -> list[Bench]:
        self.asked.append(owner)
        if self.down:
            raise WorkshopUnavailable()
        return [Bench(b, owner.household_id, owner.person_id, "B", EPOCH, None) for b in self.mine]

    async def open(self, owner: Owner, title: str) -> Bench:
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

    async def log(self, owner: Owner, bench_id: int) -> list[Logged]:
        raise NotImplementedError

    async def unseen(self, pause_s: float, limit: int, listed: int) -> tuple[Unseen, ...]:
        raise NotImplementedError

    async def reaction_ages(self, bench_id: int, window_s: float) -> tuple[float, ...]:
        raise NotImplementedError

    async def reacted(self, household_id: int, bench_id: int, to_seq: int, keep_s: float) -> None:
        raise NotImplementedError


@pytest.fixture
def live() -> FakeLive:
    fake = FakeLive()
    services.register(Live, fake)
    services.register(Tools, Everyday())
    return fake


@pytest.fixture
def shop() -> Benches:
    fake = Benches()
    services.register(Workshop, fake)
    return fake


def offered(inbound: Inbound) -> list[str]:
    return [s.name for s in asyncio.run(for_turn(inbound).catalogue()).specs]


def move(**args: object) -> ToolResult:
    return asyncio.run(MovePageTools(10, 1).call(ToolCall("m", "move_page", args)))


@pytest.mark.parametrize("inbound", [WEB, BENCH_TALK])
def test_moving_the_page_is_offered_where_the_speakers_own_page_is_the_channel(live: FakeLive,
                                                                               inbound: Inbound) -> None:
    assert "move_page" in offered(inbound)


@pytest.mark.parametrize("inbound", [DM, VOICE, replace(WEB, on_page=False), replace(WEB, speaker_id=None)])
def test_it_is_not_offered_on_any_other_thread_or_without_a_known_speaker(live: FakeLive, inbound: Inbound) -> None:
    assert "move_page" not in offered(inbound)


@pytest.mark.parametrize(("to", "room"), [("chat", "her"), ("workshop", "workshop"), ("memory", "memory"),
                                          ("devices", "devices"), ("connections", "connections")])
def test_a_move_to_a_room_publishes_it_to_the_speakers_screens(live: FakeLive, to: str, room: PageRoom) -> None:
    got = move(to=to)
    assert not got.is_error and json.loads(got.content) == {"moved_to": room, "bench_id": None}
    assert live.published == [PageMoved(Shown(10, 1), room)]


def test_a_move_to_one_of_the_speakers_open_benches_names_it(live: FakeLive, shop: Benches) -> None:
    got = move(to="bench", bench_id=6)
    assert not got.is_error and live.published == [PageMoved(Shown(10, 1), "workshop", 6)]
    assert shop.asked == [Owner(10, 1)]


@pytest.mark.parametrize(("args", "outcome"), [
    ({"to": "bench", "bench_id": 9}, "no_such_bench"), ({"to": "bench"}, "bad_arguments"),
    ({"to": "bench", "bench_id": "4"}, "bad_arguments"), ({"to": "bench", "bench_id": True}, "bad_arguments"),
    ({"to": "kitchen"}, "bad_arguments"), ({}, "bad_arguments")])
def test_a_bench_not_the_speakers_own_open_one_or_a_bad_destination_moves_nothing(
        live: FakeLive, shop: Benches, args: dict[str, object], outcome: str) -> None:
    got = move(**args)
    assert got.is_error and got.content.startswith(outcome + ":") and live.published == []


def test_benches_out_of_reach_move_nothing(live: FakeLive, shop: Benches) -> None:
    shop.down = True
    got = move(to="bench", bench_id=4)
    assert got.is_error and got.content.startswith("unavailable:") and live.published == []


def test_a_move_is_shown_to_its_persons_screens_alone() -> None:
    moved = PageMoved(Shown(10, 1), "workshop", 4)
    watchers = [Viewer(10, 1), Viewer(10, 2), Viewer(11, 1), DeviceViewer(10, 7)]
    assert [shown_to(moved, w) for w in watchers] == [True, False, False, False]


def test_a_move_is_for_a_person_and_only_the_workshop_has_benches() -> None:
    with pytest.raises(ValueError):
        PageMoved(Shown(10, None), "her")
    with pytest.raises(ValueError):
        PageMoved(Shown(10, 1), "memory", 4)


@pytest.mark.parametrize("moved", [PageMoved(Shown(10, 1), "her"), PageMoved(Shown(10, 1), "workshop", 4)])
def test_a_move_survives_the_wire_between_pods_and_reaches_the_screen_as_ids(moved: PageMoved) -> None:
    assert decode(encode(moved)) == moved
    assert set(json.loads(encode(moved))) == {"type", "household_id", "person_id", "device_id", "room", "bench_id"}
    assert wire(moved).root == LivePage(type="page", room=moved.room, bench_id=moved.bench_id)


def test_a_move_logs_one_line_of_ids(live: FakeLive, shop: Benches, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.tools")
    move(to="bench", bench_id=4)
    fields = [getattr(r, "fields") for r in caplog.records if r.getMessage() == "tools.call"]
    assert len(fields) == 1 and fields[0]["tool"] == "move_page" and fields[0]["outcome"] == "ok"
    assert fields[0]["room"] == "workshop" and fields[0]["bench"] == 4
