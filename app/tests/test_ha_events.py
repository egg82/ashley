"""`HaHouse` events over a stand-in Home Assistant: a nest camera's device from the entity registry, its events from the
media source's browse, and an event's preview from the thumbnail path the browse gives. A camera of another platform, or a
device the source does not know, has none."""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from ashley.home_assistant.client import connect
from ashley.home_assistant.ha_house import HaHouse
from ashley.home_assistant.house import Event, HouseUnavailable, Preview, Snapshot
from ashley.home_assistant.house_settings import HouseSettings
from house_stand_support import TOKEN, Stand, serving

SETTINGS = HouseSettings(timeout_s=5.0, socket_max_bytes=1_000_000, entity_tries=1, entity_wait_s=0.0)
ROOT = "media-source://nest/"
FIRST, SECOND = f"{ROOT}dev-a/ev-1", f"{ROOT}dev-a/ev-2"
THUMB = "/api/nest/event_media/dev-a/ev-1/thumbnail"


def world() -> Stand:
    stand = Stand()
    stand.registries = {"entity": [
        {"entity_id": "camera.zq_gate", "device_id": "dev-a", "platform": "nest"},
        {"entity_id": "camera.zq_shed", "device_id": "dev-b", "platform": "nest"},
        {"entity_id": "camera.zq_yard", "device_id": "dev-c", "platform": "generic"}]}
    stand.browsable = {
        ROOT + "dev-a": [{"media_content_id": FIRST, "title": "Gate @ 2026-01-02 03:04:05", "thumbnail": THUMB},
                         {"media_content_id": SECOND, "title": "Gate @ 2026-01-02 02:00:00", "thumbnail": None}],
        ROOT + "dev-b": [], ROOT + "dev-c": [{"media_content_id": ROOT + "dev-c/x", "title": "Yard", "thumbnail": "/t"}]}
    stand.thumbnails = {THUMB: (200, "image/gif", b"GIF89a-made-up")}
    return stand


def run[T](stand: Stand, work: Callable[[HaHouse], Awaitable[T]]) -> T:
    async def go() -> T:
        with serving(stand) as base:
            client = connect(base, TOKEN)
            try:
                return await work(HaHouse(client, SETTINGS))
            finally:
                await client.http.aclose()
    return asyncio.run(go())


def test_a_nest_cameras_events_come_from_its_device_in_the_order_the_house_lists_them() -> None:
    stand = world()
    got = run(stand, lambda h: h.events("camera.zq_gate"))
    assert got == (Event(FIRST, "Gate @ 2026-01-02 03:04:05"), Event(SECOND, "Gate @ 2026-01-02 02:00:00"))
    assert [c["media_content_id"] for c in stand.commands if c["type"] == "media_source/browse_media"] == [ROOT + "dev-a"]


def test_a_device_with_no_stored_events_has_none() -> None:
    assert run(world(), lambda h: h.events("camera.zq_shed")) == ()


@pytest.mark.parametrize("camera", ["camera.zq_yard", "camera.zq_unregistered"])
def test_a_camera_of_another_platform_or_not_registered_has_none_and_the_media_source_is_not_asked(camera: str) -> None:
    stand = world()
    assert run(stand, lambda h: h.events(camera)) == ()
    assert not [c for c in stand.commands if c["type"] == "media_source/browse_media"]


def test_a_device_the_media_source_does_not_know_has_none_not_an_error() -> None:
    stand = world()
    del stand.browsable[ROOT + "dev-a"]
    assert run(stand, lambda h: h.events("camera.zq_gate")) == ()


def test_an_events_preview_is_fetched_from_the_thumbnail_path_the_browse_gave() -> None:
    stand = world()
    got = run(stand, lambda h: h.event_picture("camera.zq_gate", FIRST))
    assert got == Preview("Gate @ 2026-01-02 03:04:05", Snapshot(b"GIF89a-made-up", "image/gif"))
    assert ("rest", f"GET {THUMB}", f"Bearer {TOKEN}") in stand.calls


@pytest.mark.parametrize("event", [SECOND, ROOT + "dev-a/ev-9", ROOT + "dev-c/x"])
def test_an_event_with_no_preview_or_not_the_cameras_has_no_picture(event: str) -> None:
    assert run(world(), lambda h: h.event_picture("camera.zq_gate", event)) is None


def test_a_browse_the_house_cannot_answer_is_unavailable() -> None:
    stand = world()
    stand.token = "other"
    with pytest.raises(HouseUnavailable):
        run(stand, lambda h: h.events("camera.zq_gate"))
