"""Blind contract tests for `MovePageTools` (docstrings, `decisions.md` "She moves the person's page herself", and the
`PageMoved` type). Each test names the contract line (MP-n, Tools-1) in `notes/blind-house-move.txt`."""

import asyncio
from typing import Any, get_args

import pytest
from ashley import logs
from ashley.inference.model import ToolCall
from ashley.live.events import PageMoved, PageRoom, Shown, Viewer, DeviceViewer, shown_to
from ashley.live.live import Live
from ashley.tools.move_page import MovePageTools
from ashley.workshop.workshop import Workshop
from ashley import services
from conversations_support import events
from house_move_support import CLOSED, HOUSEHOLD, OPEN, OTHER_PERSON, OTHERS, PERSON, Benches, Page, page as page

ROOMS: dict[str, PageRoom] = {"workshop": "workshop", "memory": "memory", "devices": "devices", "chat": "her",
                              "connections": "connections"}


# MP-1: the catalogue ------------------------------------------------------------------------------------------------

def test_the_catalogue_offers_move_page_with_its_five_destinations() -> None:
    (spec,) = asyncio.run(MovePageTools(HOUSEHOLD, PERSON).catalogue()).specs
    props: Any = spec.parameters["properties"]
    assert spec.name == "move_page"
    assert set(props["to"]["enum"]) == {"chat", "workshop", "bench", "memory", "devices", "connections"}
    assert props["bench_id"]["type"] == "integer"
    assert spec.parameters["required"] == ["to"]


# MP-2: one PageMoved, to the speaker's screens alone ------------------------------------------------------------------

@pytest.mark.parametrize("to", sorted(ROOMS))
def test_a_room_move_publishes_one_page_moved_to_the_speaker_alone(page: Page, to: str) -> None:
    result = page.move(to=to)
    assert not result.is_error and result.call_id == "m1"
    assert page.moved() == [PageMoved(Shown(HOUSEHOLD, PERSON, None), ROOMS[to], None)]
    assert len(page.live.published) == 1


def test_every_destination_room_is_a_room_the_event_type_knows(page: Page) -> None:
    for to in ROOMS:
        page.move(to=to)
    assert {e.room for e in page.moved()} <= set(get_args(PageRoom))


def test_each_call_publishes_its_own_event(page: Page) -> None:
    page.move(to="memory")
    page.move(to="devices")
    assert [e.room for e in page.moved()] == ["memory", "devices"]


# MP-6: nobody else's screen ----------------------------------------------------------------------------------------

def test_the_event_reaches_the_speakers_screens_and_nobody_elses(page: Page) -> None:
    page.move(to="workshop")
    (event,) = page.moved()
    assert shown_to(event, Viewer(HOUSEHOLD, PERSON))
    assert not shown_to(event, Viewer(HOUSEHOLD, OTHER_PERSON))
    assert not shown_to(event, Viewer(HOUSEHOLD + 1, PERSON))
    assert not shown_to(event, DeviceViewer(HOUSEHOLD, 5))


# MP-3: a bench must be one of the speaker's open benches -------------------------------------------------------------

def test_an_open_bench_of_the_speaker_moves_the_page_to_it(page: Page) -> None:
    result = page.move(to="bench", bench_id=OPEN)
    assert not result.is_error
    assert page.moved() == [PageMoved(Shown(HOUSEHOLD, PERSON, None), "workshop", OPEN)]


@pytest.mark.parametrize("bench_id", [CLOSED, OTHERS, 0, -1, 99999])
def test_a_bench_that_is_not_the_speakers_open_one_moves_nothing(page: Page, bench_id: int) -> None:
    result = page.move(to="bench", bench_id=bench_id)
    assert result.is_error
    assert page.live.published == []


def test_a_bench_without_its_id_moves_nothing(page: Page) -> None:
    assert page.move(to="bench").is_error
    assert page.live.published == []


def test_the_benches_asked_after_are_the_speakers_own(page: Page) -> None:
    page.move(to="bench", bench_id=OPEN)
    assert page.workshop.asked
    assert {(o.household_id, o.person_id) for o in page.workshop.asked} == {(HOUSEHOLD, PERSON)}


def test_an_unreachable_workshop_is_an_error_result_not_a_raise(page: Page) -> None:
    page.workshop.down = True
    assert page.move(to="bench", bench_id=OPEN).is_error
    assert page.live.published == []


def test_a_room_move_does_not_need_the_workshop(page: Page) -> None:
    page.workshop.down = True
    assert not page.move(to="memory").is_error
    assert [e.room for e in page.moved()] == ["memory"]


def test_a_bench_id_beside_another_room_never_puts_a_bench_in_it(page: Page) -> None:
    page.move(to="memory", bench_id=OPEN)
    assert all(e.bench_id is None for e in page.moved())
    assert all(e.room == "memory" for e in page.moved())


# MP-4 / Tools-1: refusals are results, never raises ----------------------------------------------------------------

@pytest.mark.parametrize("arguments", [
    {"to": "kitchen"}, {"to": ""}, {"to": None}, {"to": 3}, {"to": ["chat"]}, {}, {"to": "Chat "}, {"to": "her"},
])
def test_a_destination_that_is_not_a_room_is_an_error_and_moves_nothing(page: Page, arguments: dict[str, object]) -> None:
    result = page.move(**arguments)
    assert result.is_error
    assert page.live.published == []


@pytest.mark.parametrize("bench_id", ["31", 31.5, None, True, [31]])
def test_a_bench_id_that_is_not_an_integer_moves_nothing(page: Page, bench_id: object) -> None:
    assert page.move(to="bench", bench_id=bench_id).is_error
    assert page.live.published == []


def test_another_tools_name_is_an_error_result(page: Page) -> None:
    result = asyncio.run(page.tools.call(ToolCall("x9", "not_a_tool", {"to": "chat"})))
    assert result.is_error and result.call_id == "x9"
    assert page.live.published == []


def test_an_unwired_live_does_not_make_a_move_raise() -> None:
    services.unregister(Live)
    services.register(Workshop, Benches({PERSON: (OPEN,)}))
    try:
        result = asyncio.run(MovePageTools(HOUSEHOLD, PERSON).call(ToolCall("m1", "move_page", {"to": "chat"})))
    finally:
        services.unregister(Workshop)
    assert result.call_id == "m1"


def test_an_error_result_says_something(page: Page) -> None:
    assert page.move(to="kitchen").content.strip()


# MP-5: one tools.call line per move, ids only --------------------------------------------------------------------

def test_a_move_logs_one_tools_call_with_its_room(page: Page, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    page.move(to="memory")
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert "memory" in line.values() and "duration_ms" in line


def test_a_bench_move_logs_its_bench_id(page: Page, capsys: pytest.CaptureFixture[str]) -> None:
    logs.setup()
    capsys.readouterr()
    page.move(to="bench", bench_id=OPEN)
    (line,) = events(capsys.readouterr().out, "tools.call")
    assert str(OPEN) in line.values()


def test_true_is_not_a_bench_id_even_when_bench_one_is_open(page: Page) -> None:
    page.workshop.open_of[PERSON] = (1,)
    assert page.move(to="bench", bench_id=True).is_error
    assert page.live.published == []
    assert not page.move(to="bench", bench_id=1).is_error
