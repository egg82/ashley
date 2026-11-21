"""The camera port and her `cameras` and `camera_look` tools over Home Assistant's adapter, against an in-memory house, an
in-memory store and Postgres Looks: a household with no camera source, or the port off, is offered nothing; a camera is
listed and looked through only when the household's `look_cameras` setting names it; the still is kept as a look on no
bench and handed to the model as an image; a camera that gives no still is said so, asked once; the household's own
failures are errors, never an empty roster; and nothing names a camera or a byte in a log."""

import io
import json
import logging
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import pytest
from PIL import Image as PilImage
from files_support import sync
from look_pictures_support import noise
from ashley import services
from ashley.cameras.cameras import Cameras
from ashley.cameras.routed import RoutedCameras
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.connections.connections import Connections
from ashley.connections.model import Port
from ashley.connections.settings import SettingValues
from ashley.connections.settings_read import NullSettingsReader, SettingsReader
from ashley.db.pool import PoolDatabase
from ashley.files.memory import MemoryStore
from ashley.files.store import NullStore, ObjectStore
from ashley.home_assistant.cameras import NAME, HaCameras
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.house import Snapshot
from ashley.inference.model import ToolCall, ToolResult
from ashley.looks.looks import Looks
from ashley.looks.postgres import PostgresLooks
from ashley.tools.camera_specs import CAMERAS, LOOK
from ashley.tools.camera_tools import CameraTools
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from contract.conversations_support import household, scalar
from homes_support import AnyHousehold
from house_double_support import MemoryHouse, state
from money_support import HeldConnections

PORCH, HALL, BACK = "camera.zq_porch", "camera.zq_hall", "camera.zq_back"
STILL = noise((64, 48))


class Settings(NullSettingsReader):
    def __init__(self, looks: tuple[str, ...] = (PORCH, HALL), off: frozenset[str] = frozenset()) -> None:
        self.looks = looks
        self.off = off

    async def of(self, household_id: int, port: Port) -> SettingValues:
        return {"look_cameras": list(self.looks)} if self.looks else {}

    async def ports_off(self, household_id: int) -> Mapping[int, frozenset[str]]:
        return {1: self.off} if self.off else {}


@asynccontextmanager
async def world(url: str) -> AsyncGenerator[tuple[MemoryHouse, int, int, int]]:
    home = household(url)
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'chat') RETURNING id",
                              (home,)))
    turn = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, text) "
                           "VALUES (%s, %s, 'person', 'look') RETURNING id", (conversation, home)))
    database = PoolDatabase(url)
    await database.open()
    made = MemoryHouse()
    made.things = [state(PORCH, "Porch", "idle"), state(HALL, "Hall", "idle"), state(BACK, "Back garden", "idle"),
                   state("light.zq", "Lamp", "on")]
    made.stills = {PORCH: Snapshot(STILL, "image/png"), HALL: None, BACK: Snapshot(STILL, "image/png")}
    held = HeldConnections()
    held.connect(home, "http://ha.test", "k", NAME)
    services.register(Connections, held)
    services.register(Homes, AnyHousehold(made))
    services.register(Cameras, RoutedCameras({NAME: HaCameras()}))
    services.register(SettingsReader, Settings())
    services.register(ObjectStore, MemoryStore())
    services.register(Looks, PostgresLooks(database))
    try:
        yield made, home, conversation, turn
    finally:
        for interface in (Connections, Homes, Cameras, SettingsReader, ObjectStore, Looks):
            services.unregister(interface)
        await database.close()


async def run(home: int, conversation: int, turn: int, name: str, arguments: dict[str, object],
              call_id: str = "c1") -> ToolResult:
    return await CameraTools(home, conversation, turn).call(ToolCall(call_id, name, arguments))


def body(result: ToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    loose: dict[str, Any] = json.loads(result.content)
    return loose


@sync
async def test_only_the_cameras_a_person_named_are_listed_each_labelled_with_its_source(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        got = body(await run(home, conversation, turn, CAMERAS, {}))
        assert got["cameras"] == [{"id": PORCH, "title": "Porch", "source": NAME},
                                  {"id": HALL, "title": "Hall", "source": NAME}]
        services.register(SettingsReader, Settings(()))
        assert body(await run(home, conversation, turn, CAMERAS, {}))["cameras"] == []


@sync
async def test_a_still_is_given_as_an_image_kept_as_a_look_on_no_bench(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        got = await run(home, conversation, turn, LOOK, {"camera": PORCH})
        shown = body(got)
        (picture,) = got.images
        assert picture.media_type == "image/jpeg" and PilImage.open(io.BytesIO(picture.data)).size == (64, 48)
        assert shown["picture"] == "follows in this result" and "taken" in shown
        (kept,) = await services.get(Looks).in_conversation(home, conversation)
        assert (kept.call_id, kept.bench_id, kept.piece_id, kept.media_type) == ("c1", None, None, "image/jpeg")
        assert await services.get(ObjectStore).get(f"look/{home}/{kept.sha256}") == picture.data


@sync
async def test_a_camera_that_gives_no_still_says_so_asks_once_and_keeps_nothing(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        got = await run(home, conversation, turn, LOOK, {"camera": HALL})
        assert got.is_error and got.content.startswith("no_still") and got.images == ()
        assert await services.get(Looks).in_conversation(home, conversation) == []
        assert house.reads == 2


@sync
async def test_a_camera_not_named_is_not_looked_through_and_the_house_is_not_asked_for_it(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        got = await run(home, conversation, turn, LOOK, {"camera": BACK})
        assert got.is_error and got.content.startswith("bad_arguments")
        assert house.stills[BACK] is not None and await services.get(Looks).in_conversation(home, conversation) == []


@sync
@pytest.mark.parametrize("arguments", [{}, {"camera": ""}, {"camera": 4}, {"camera": PORCH, "region": "x"}])
async def test_bad_arguments_ask_the_house_nothing(db_url: str, arguments: dict[str, object]) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        assert (await run(home, conversation, turn, LOOK, arguments)).content.startswith("bad_arguments")
        assert house.reads == 0


@sync
async def test_a_turn_takes_only_so_many_looks(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        for n in range(4):
            assert not (await run(home, conversation, turn, LOOK, {"camera": PORCH}, f"c{n}")).is_error
        assert (await run(home, conversation, turn, LOOK, {"camera": PORCH}, "c9")).content.startswith("limit")


@sync
@pytest.mark.parametrize("fault", ["down", "not_a_picture"])
async def test_a_house_that_cannot_give_a_still_is_an_error_and_a_roster_it_cannot_read_is_unread(
        db_url: str, fault: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        house.down = True
        assert body(await run(home, conversation, turn, CAMERAS, {}))["unread"] == [NAME]
        assert (await run(home, conversation, turn, LOOK, {"camera": PORCH})).content.startswith("unreachable")
        house.down = False
        house.stills[PORCH] = Snapshot(b"not an image", "image/png")
        assert (await run(home, conversation, turn, LOOK, {"camera": PORCH})).content.startswith("unreadable")
        assert await services.get(Looks).in_conversation(home, conversation) == []


@sync
async def test_a_port_switched_off_or_no_store_offers_nothing(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        tools = CameraTools(home, conversation, turn)
        assert [s.name for s in (await tools.catalogue()).specs] == [CAMERAS, LOOK]
        services.register(SettingsReader, Settings(off=frozenset({"camera"})))
        assert (await tools.catalogue()).specs == ()
        assert (await run(home, conversation, turn, LOOK, {"camera": PORCH})).content.startswith("not_connected")
        services.register(SettingsReader, Settings())
        services.register(ObjectStore, NullStore())
        assert (await tools.catalogue()).specs == ()
        assert (await CameraTools(home + 1, conversation, turn).catalogue()).specs == ()


@sync
async def test_both_tools_are_reads_that_are_outside_words(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        specs = (await CameraTools(home, conversation, turn).catalogue()).specs
        assert [(s.reads, s.outside) for s in specs] == [(True, True), (True, True)]


@sync
async def test_the_log_names_ids_and_counts_never_a_camera_or_a_byte(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        with caplog.at_level(logging.DEBUG):
            await run(home, conversation, turn, CAMERAS, {})
            await run(home, conversation, turn, LOOK, {"camera": PORCH})
        text = caplog.text
        assert "camera.look" in text and "camera.read" in text
        assert "Porch" not in text and PORCH not in text and "zq_porch" not in text


@sync
async def test_the_tools_are_offered_to_a_known_speaker_with_a_turn(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        satellite = Inbound(household_id=home, thread="device:7", text="who is at the door?", kind="command",
                            medium="spoken", audience="present", speaker_id=1, shared=True, place="kitchen",
                            channel="voice", heard_as=1)
        assert "camera" not in sources(satellite)
        assert "camera" in sources(satellite, conversation_id=conversation, turn=(conversation, turn))
