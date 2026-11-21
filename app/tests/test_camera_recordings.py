"""A camera's recordings through the Cameras port and the `camera_recordings` tool and `camera_look`'s `recording`, over
Home Assistant's adapter against an in-memory house: the same `look_cameras` list governs them, a list is capped and
newest first as the source gives it, a recording's picture is the middle frame of its preview and is kept like a live
look, a title is given as written and a missing time is absent, and nothing names a title or a byte in a log."""

import io
import json
import logging
from typing import Any

import pytest
from files_support import sync
from PIL import Image as PilImage
from ashley import services
from ashley.cameras.cameras import Cameras
from ashley.home_assistant.house import Event, Snapshot
from ashley.inference.model import ToolResult
from ashley.looks.looks import Looks
from ashley.tools.camera_specs import LOOK, RECORDINGS
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template
from house_double_support import MemoryHouse
from test_camera_port import BACK, HALL, PORCH, body, run, world

TITLE = "Gate @ 2026-01-02 03:04:05"


def gif(colours: tuple[tuple[int, int, int], ...]) -> bytes:
    frames = [PilImage.new("RGB", (32, 24), c) for c in colours]
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0, disposal=2)
    return out.getvalue()


RED, GREEN, BLUE = (250, 10, 10), (10, 250, 10), (10, 10, 250)


def keep(house: MemoryHouse, camera: str, count: int, preview: bytes) -> list[Event]:
    events = [Event(f"media-source://nest/d/{camera}-{n}", f"Gate @ 2026-01-02 0{n}:00:00") for n in range(count)]
    house.captured[camera] = events
    house.previews = {(camera, e.id): Snapshot(preview, "image/gif") for e in events}
    return events


def middle(result: ToolResult) -> tuple[int, int, int]:
    (picture,) = result.images
    pixel = PilImage.open(io.BytesIO(picture.data)).convert("RGB").getpixel((16, 12))
    assert isinstance(pixel, tuple)
    return pixel[0], pixel[1], pixel[2]


def near(got: tuple[int, int, int], want: tuple[int, int, int]) -> bool:
    return all(abs(a - b) < 40 for a, b in zip(got, want, strict=True))


@sync
async def test_recordings_are_listed_newest_first_as_the_source_gives_them_capped_with_their_titles_as_written(
        db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        events = keep(house, PORCH, 5, gif((RED, GREEN, BLUE)))
        got = body(await run(home, conversation, turn, RECORDINGS, {"camera": PORCH}))
        assert got["recordings"] == [{"id": e.id, "title": e.title} for e in events[:3]]


@sync
async def test_a_camera_with_no_recordings_has_an_empty_list_not_an_error(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        assert body(await run(home, conversation, turn, RECORDINGS, {"camera": PORCH}))["recordings"] == []


@sync
async def test_a_camera_she_may_not_look_through_has_no_recordings_for_her_either(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, BACK, 2, gif((RED, GREEN, BLUE)))
        listed = await run(home, conversation, turn, RECORDINGS, {"camera": BACK})
        looked = await run(home, conversation, turn, LOOK, {"camera": BACK, "recording": event.id})
        assert listed.content.startswith("bad_arguments") and looked.content.startswith("bad_arguments")
        assert looked.images == () and await services.get(Looks).in_conversation(home, conversation) == []


@sync
async def test_a_recording_look_gives_the_middle_frame_of_its_preview_kept_as_a_look_with_the_title_and_no_time(
        db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 1, gif((RED, GREEN, BLUE)))
        house.captured[PORCH] = [Event(event.id, TITLE)]
        got = await run(home, conversation, turn, LOOK, {"camera": PORCH, "recording": event.id})
        shown = body(got)
        assert shown == {"picture": "follows in this result", "recording": TITLE}
        assert near(middle(got), GREEN)
        (kept,) = await services.get(Looks).in_conversation(home, conversation)
        assert (kept.call_id, kept.bench_id, kept.media_type) == ("c1", None, "image/jpeg")


@sync
async def test_a_single_frame_preview_is_its_own_middle(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 1, gif((BLUE,)))
        assert near(middle(await run(home, conversation, turn, LOOK, {"camera": PORCH, "recording": event.id})), BLUE)


@sync
async def test_a_live_look_still_states_when_it_was_taken_and_names_no_recording(db_url: str) -> None:
    async with world(db_url) as (_, home, conversation, turn):
        shown = body(await run(home, conversation, turn, LOOK, {"camera": PORCH}))
        assert "taken" in shown and "recording" not in shown


@sync
async def test_a_recording_that_is_not_the_cameras_is_refused_and_keeps_nothing(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        keep(house, PORCH, 1, gif((RED, GREEN)))
        (other,) = keep(house, HALL, 1, gif((RED, GREEN)))
        got = await run(home, conversation, turn, LOOK, {"camera": PORCH, "recording": other.id})
        assert got.content.startswith("bad_arguments") and got.images == ()
        assert await services.get(Looks).in_conversation(home, conversation) == []


@sync
async def test_a_recording_look_counts_against_the_turns_looks(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 1, gif((RED, GREEN)))
        for n in range(4):
            assert not (await run(home, conversation, turn, LOOK, {"camera": PORCH, "recording": event.id}, f"r{n}")).is_error
        assert (await run(home, conversation, turn, LOOK, {"camera": PORCH}, "c9")).content.startswith("limit")


@sync
async def test_a_preview_that_is_not_a_picture_is_unrecognised_and_a_house_down_is_unreachable(db_url: str) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 1, b"not a picture")
        got = await run(home, conversation, turn, LOOK, {"camera": PORCH, "recording": event.id})
        assert got.content.startswith("unrecognised") and got.images == ()
        house.down = True
        assert (await run(home, conversation, turn, RECORDINGS, {"camera": PORCH})).content.startswith("unreachable")


@sync
@pytest.mark.parametrize("arguments", [{}, {"camera": ""}, {"camera": PORCH, "x": 1}])
async def test_bad_recordings_arguments_ask_the_house_nothing(db_url: str, arguments: dict[str, object]) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        assert (await run(home, conversation, turn, RECORDINGS, arguments)).content.startswith("bad_arguments")
        assert house.reads == 0


@sync
@pytest.mark.parametrize("arguments", [{"camera": PORCH, "recording": ""}, {"camera": PORCH, "recording": 4},
                                       {"camera": PORCH, "recording": "x" * 201}, {"camera": PORCH, "region": "a"}])
async def test_bad_look_arguments_for_a_recording_ask_the_house_nothing(db_url: str, arguments: dict[str, object]) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        assert (await run(home, conversation, turn, LOOK, arguments)).content.startswith("bad_arguments")
        assert house.reads == 0


@sync
async def test_the_port_raises_the_unknowns_by_name(db_url: str) -> None:
    from ashley.cameras.model import NoSuchCamera, NoSuchRecording
    async with world(db_url) as (house, home, _, _):
        keep(house, PORCH, 1, gif((RED, GREEN)))
        cameras = services.get(Cameras)
        with pytest.raises(NoSuchCamera):
            await cameras.recordings(home, "camera.zq_nope")
        with pytest.raises(NoSuchRecording):
            await cameras.look_recording(home, PORCH, "media-source://nest/d/none")
        assert (await cameras.look_recording(home, PORCH, house.captured[PORCH][0].id)).taken is None


@sync
async def test_the_log_names_counts_never_a_title_or_a_byte(db_url: str, caplog: pytest.LogCaptureFixture) -> None:
    async with world(db_url) as (house, home, conversation, turn):
        (event, *_) = keep(house, PORCH, 2, gif((RED, GREEN, BLUE)))
        with caplog.at_level(logging.DEBUG):
            await run(home, conversation, turn, RECORDINGS, {"camera": PORCH})
            await run(home, conversation, turn, LOOK, {"camera": PORCH, "recording": event.id})
        assert "camera.recordings" in caplog.text and "camera.look" in caplog.text
        assert "Gate @" not in caplog.text and "2026-01-02" not in caplog.text and "nest/d" not in caplog.text


@sync
async def test_camera_look_takes_an_optional_recording(db_url: str) -> None:
    from ashley.tools.camera_tools import CameraTools
    async with world(db_url) as (_, home, conversation, turn):
        specs = (await CameraTools(home, conversation, turn).catalogue()).specs
        loose: dict[str, Any] = json.loads(json.dumps(specs[1].parameters))
        assert set(loose["properties"]) == {"camera", "recording"} and loose["required"] == ["camera"]
