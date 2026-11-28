"""Her `bench_show`: it publishes `BenchShown` to the speaker's screens with the pieces that are on the bench, stores
nothing (the Workshop is read and never written), ignores ids that are not on the bench, and answers an error she can read
when none is left or the arguments are not one of the two shapes; the event survives the wire between pods."""

import asyncio
import json

import pytest
from ashley import services
from ashley.api.live import wire
from ashley.api.live_models import LiveShow
from ashley.channels.turn_tools import for_turn
from ashley.channels.model import Inbound
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.events import BenchShown, Shown, decode, encode, shown_to, Viewer
from ashley.live.live import Live
from ashley.tools.bench_show import BenchShowTools
from ashley.workshop.model import Piece, Place, Text
from ashley.workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from bench_tools_support import FakeWorkshop
from live_support import FakeLive

OWNER = Shown(10, 1)


def piece(pid: int) -> Piece:
    return Piece(pid, "note", Text(f"title {pid}", "body"), 1, Place(pid, "medium"), pid)


@pytest.fixture
def shop() -> FakeWorkshop:
    fake = FakeWorkshop(pieces=(piece(3), piece(5), piece(8)))
    services.register(Workshop, fake)
    return fake


@pytest.fixture
def live() -> FakeLive:
    fake = FakeLive()
    services.register(Live, fake)
    return fake


def show(**args: object) -> ToolResult:
    return asyncio.run(BenchShowTools(10, 1, 4).call(ToolCall("s", "bench_show", args)))


def test_the_pieces_asked_for_are_published_to_the_owner_and_nothing_is_stored(shop: FakeWorkshop, live: FakeLive) -> None:
    got = show(piece_ids=[5, 3])
    assert not got.is_error and json.loads(got.content) == {"shown": [5, 3], "fold": False, "ignored": []}
    assert live.published == [BenchShown(OWNER, 4, (5, 3), False)]
    assert shop.applied == [] and shop.turn_undos == []


def test_ids_not_on_the_bench_are_dropped_and_said(shop: FakeWorkshop, live: FakeLive) -> None:
    got = show(piece_ids=[8, 99, 8], fold=True)
    assert json.loads(got.content) == {"shown": [8], "fold": True, "ignored": [99]}
    assert live.published == [BenchShown(OWNER, 4, (8,), True)]


def test_all_is_the_whole_bench_and_publishes_no_ids(shop: FakeWorkshop, live: FakeLive) -> None:
    got = show(all=True)
    assert json.loads(got.content)["shown"] == "all"
    assert live.published == [BenchShown(OWNER, 4, (), False)]


def test_with_no_piece_left_it_is_an_error_she_can_read_and_nothing_is_published(shop: FakeWorkshop, live: FakeLive) -> None:
    got = show(piece_ids=[99])
    assert got.is_error and "none of those pieces is on the bench" in got.content
    assert live.published == []


@pytest.mark.parametrize("args", [{}, {"piece_ids": [3], "all": True}, {"piece_ids": "3"}, {"piece_ids": [True]},
                                  {"all": "yes"}, {"piece_ids": [3], "fold": 1}, {"piece_ids": [3], "zoom": 2}])
def test_arguments_that_are_not_pieces_or_all_are_refused(shop: FakeWorkshop, live: FakeLive, args: dict[str, object]) -> None:
    assert show(**args).is_error
    assert live.published == []


@pytest.mark.parametrize("down", [BenchNotFound(), WorkshopUnavailable()])
def test_a_bench_that_cannot_be_read_is_an_error_and_publishes_nothing(shop: FakeWorkshop, live: FakeLive, down: Exception) -> None:
    shop.raises = down
    assert show(piece_ids=[3]).is_error
    assert live.published == []


def test_it_is_offered_on_a_bench_turn_only(shop: FakeWorkshop, live: FakeLive) -> None:
    on_bench = Inbound(household_id=10, thread="bench:4", text="hi", kind="brainstorm", medium="text", audience="owner",
                       speaker_id=1, shared=False, place=None, channel="web", bench_id=4)
    elsewhere = Inbound(household_id=10, thread="person:1:web", text="hi", kind="chat", medium="text", audience="owner",
                        speaker_id=1, shared=False, place=None, channel="web")
    assert "bench_show" in _offered(on_bench) and "bench_show" not in _offered(elsewhere)


def _offered(inbound: Inbound) -> list[str]:
    return [s.name for s in asyncio.run(for_turn(inbound).catalogue()).specs]


def test_the_event_is_shown_to_its_owner_alone_and_survives_the_wire() -> None:
    event = BenchShown(OWNER, 4, (5, 3), True)
    assert decode(encode(event)) == event
    assert wire(event).root == LiveShow(type="show", bench_id=4, piece_ids=[5, 3], fold=True)
    assert shown_to(event, Viewer(10, 1)) and not shown_to(event, Viewer(10, 2))
    with pytest.raises(ValueError):
        BenchShown(Shown(10, None), 4, (), False)
