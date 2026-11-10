"""Her `bench_cue(piece_id, action, seconds?)` over the real workshop: the catalogue offers it, an accepted cue answers
with the piece and tells the owner's screens, every refusal and bad argument is an error result that tells no one and
logs nothing, and the seconds boundaries hold through the tool as through `decide`."""

import json
import math

import pytest
from ashley.inference.model import ToolCall, ToolResult
from ashley.live.events import Shown
from ashley.tools.bench_tools import BenchTools
from ashley.workshop.embed import MAX_START
from bench_cue_blind_support import HER, add_note, add_video, changed, cued, workshop, world
from contract.conversations_support import run
from live_support import FakeLive


async def cue_call(tools: BenchTools, **args: object) -> ToolResult:
    return await tools.call(ToolCall("c", "bench_cue", args))


def test_the_catalogue_offers_bench_cue_with_its_arguments(db_url: str) -> None:
    w = world(db_url)

    async def scenario() -> None:
        catalogue = await BenchTools(w.alana.household_id, w.alana.person_id, 1).catalogue()
        spec = next(s for s in catalogue.specs if s.name == "bench_cue")
        schema = json.loads(json.dumps(spec.parameters))
        assert set(schema["properties"]) == {"piece_id", "action", "seconds"}
        assert schema["properties"]["action"]["enum"] == ["play", "pause", "seek"]
        assert set(schema["required"]) == {"piece_id", "action"}
        assert not spec.reads

    run(scenario())


def test_an_accepted_cue_answers_with_its_piece_and_tells_the_owner_once(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench = await shop.open(w.alana, "tv")
            await shop.apply(w.alana, bench.id, add_video())
            tools = BenchTools(w.alana.household_id, w.alana.person_id, bench.id)
            seek = await cue_call(tools, piece_id=1, action="seek", seconds=42)
            play = await cue_call(tools, piece_id=1, action="play")
            pause = await cue_call(tools, piece_id=1, action="pause")
            assert not (seek.is_error or play.is_error or pause.is_error)
            assert json.loads(seek.content)["piece_id"] == 1
            assert [(c.piece_id, c.action, c.seconds) for c in cued(live)] == [(1, "seek", 42.0), (1, "play", None),
                                                                              (1, "pause", None)]
            assert {c.shown for c in cued(live)} == {Shown(w.alana.household_id, w.alana.person_id)}
            assert [c.seq for c in changed(live)] == [1]
            logged = await shop.log(w.alana, bench.id)
            assert [r.by.author for r in logged[1:]] == ["ashley"] * 3

    run(scenario())


@pytest.mark.parametrize("seconds", [0, 0.0, 1.5, MAX_START - 1, MAX_START])
def test_a_seek_inside_the_range_is_accepted_through_the_tool(db_url: str, seconds: float) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench = await shop.open(w.alana, "tv")
            await shop.apply(w.alana, bench.id, add_video())
            got = await cue_call(BenchTools(w.alana.household_id, w.alana.person_id, bench.id), piece_id=1, action="seek",
                                 seconds=seconds)
            assert not got.is_error
            assert [c.seconds for c in cued(live)] == [float(seconds)]

    run(scenario())


REFUSED = [
    ({"piece_id": 1, "action": "seek"}, "bad_cue"),
    ({"piece_id": 1, "action": "play", "seconds": 0}, "bad_cue"),
    ({"piece_id": 1, "action": "pause", "seconds": 12}, "bad_cue"),
    ({"piece_id": 1, "action": "seek", "seconds": -1}, "bad_cue"),
    ({"piece_id": 1, "action": "seek", "seconds": -0.001}, "bad_cue"),
    ({"piece_id": 1, "action": "seek", "seconds": MAX_START + 1}, "bad_cue"),
    ({"piece_id": 1, "action": "seek", "seconds": MAX_START + 0.5}, "bad_cue"),
    ({"piece_id": 2, "action": "play"}, "not_video"),
    ({"piece_id": 2, "action": "seek", "seconds": -1}, "not_video"),
    ({"piece_id": 77, "action": "play"}, "no_such_piece"),
]


@pytest.mark.parametrize(("args", "why"), REFUSED)
def test_a_refused_cue_is_an_error_naming_its_reason_and_tells_no_one(db_url: str, args: dict[str, object], why: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench = await shop.open(w.alana, "tv")
            await shop.apply(w.alana, bench.id, add_video())
            await shop.apply(w.alana, bench.id, add_note(HER))
            told = len(live.published)
            got = await cue_call(BenchTools(w.alana.household_id, w.alana.person_id, bench.id), **args)
            assert got.is_error and why in got.content
            assert len(live.published) == told and cued(live) == []

    run(scenario())


BAD_ARGUMENTS = [
    {"piece_id": 1, "action": "rewind"},
    {"piece_id": 1, "action": ""},
    {"piece_id": 1},
    {"action": "play"},
    {"piece_id": "one", "action": "play"},
    {"piece_id": 1, "action": "play", "volume": 3},
    {"piece_id": 1, "action": "seek", "seconds": "12"},
    {"piece_id": 1, "action": "seek", "seconds": True},
    {"piece_id": 1, "action": "seek", "seconds": [5]},
    {"piece_id": 1, "action": "seek", "seconds": math.nan},
    {"piece_id": 1, "action": "seek", "seconds": math.inf},
    {"piece_id": 1, "action": "seek", "seconds": -math.inf},
]


@pytest.mark.parametrize("args", BAD_ARGUMENTS)
def test_bad_arguments_are_an_error_that_changes_and_tells_nothing(db_url: str, args: dict[str, object]) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench = await shop.open(w.alana, "tv")
            await shop.apply(w.alana, bench.id, add_video())
            told = len(live.published)
            got = await cue_call(BenchTools(w.alana.household_id, w.alana.person_id, bench.id), **args)
            assert got.is_error
            assert len(live.published) == told and cued(live) == []
            assert len(await shop.log(w.alana, bench.id)) == 1

    run(scenario())


def test_her_cue_on_another_households_bench_is_an_error_and_tells_no_one(db_url: str) -> None:
    w, live = world(db_url), FakeLive()

    async def scenario() -> None:
        async with workshop(db_url, live) as shop:
            bench = await shop.open(w.alana, "tv")
            await shop.apply(w.alana, bench.id, add_video())
            for stranger in (w.sam, w.zed):
                got = await cue_call(BenchTools(stranger.household_id, stranger.person_id, bench.id), piece_id=1,
                                     action="play")
                assert got.is_error
            assert cued(live) == [] and len(await shop.log(w.alana, bench.id)) == 1

    run(scenario())
