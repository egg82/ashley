"""Bambuddy's printer cameras behind the Cameras port, over a fake Bambuddy built from its documented and live-read
response shapes: one camera per printer it has, listed and looked through only when the Bambuddy connection's
`look_cameras` names it, a still taken with a stream token minted for that look, a printer's timelapses as its
recordings, the ids of two sources never meeting, one source down leaving the other's cameras, and no printer name or byte
in a log."""

import logging
from collections.abc import Iterator, Mapping

import httpx2
import pytest
from files_support import sync
from ashley import services
from ashley.bambuddy.cameras import NAME, BambuddyCameras
from ashley.bambuddy.client import Bambuddy, BambuddyFailed, HttpBambuddy
from ashley.bambuddy.kind import BAMBUDDY
from ashley.cameras.cameras import Cameras
from ashley.cameras.model import Camera, CamerasFailed, Candidate, NoLiveFeed, NoSuchCamera, NoSuchRecording
from ashley.cameras.routed import RoutedCameras
from ashley.connections import ports
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Opened, Port
from ashley.connections.settings import EntityList, SettingValue, SettingValues
from ashley.connections.settings_read import NullSettingsReader, SettingsReader, StoredSettings
from ashley.home_assistant import cameras as ha
from ashley.home_assistant.homes import Homes
from ashley.home_assistant.house import Snapshot
from bambuddy_support import BASE, JPEG, KEY, FakeBambuddy, archive, held, printer
from homes_support import AnyHousehold
from house_double_support import MemoryHouse, state
from look_pictures_support import noise

HOME = 10
SHED, LOFT = "printer.1", "printer.2"
PORCH = "camera.zq_porch"
FRONT, MIDDLE, LAST = b"\xff\xd8\xff\xe0front", b"\xff\xd8\xff\xe0middle", b"\xff\xd8\xff\xe0last"


class Settings(NullSettingsReader):
    """Each connection's own settings by id (`stored`), and Home Assistant's, which its adapter reads by port (`of`)."""

    def __init__(self, by_connection: Mapping[int, SettingValues], house: SettingValues | None = None,
                 down: bool = False) -> None:
        self.by_connection = by_connection
        self.house = house or {}
        self.down = down

    async def of(self, household_id: int, port: Port) -> SettingValues:
        return self.house

    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        if self.down:
            raise ConnectionsUnavailable("down")
        return StoredSettings(1, dict(self.by_connection.get(connection_id, {})), None, None)


def named(*ids: str) -> dict[str, SettingValue]:
    return {"look_cameras": list(ids)}


@pytest.fixture
def fake() -> Iterator[FakeBambuddy]:
    found = FakeBambuddy()
    found.answers["/api/v1/printers/"] = [printer(1, "Shed X1C"), printer(2, "Loft P1S")]
    found.archives = [archive(31, 1, "Benchy"), archive(30, 1, None, timelapse=False), archive(29, 1, None),
                      archive(40, 2, "Vase")]
    found.frames = {31: [FRONT, MIDDLE, LAST], 29: [FRONT, LAST]}
    connections = held(HOME)
    services.register(Connections, connections)
    services.register(Bambuddy, found.client())
    services.register(SettingsReader, Settings({1: {}, 2: named(SHED)}))
    services.register(Cameras, RoutedCameras({NAME: BambuddyCameras()}, 3))
    yield found


def _ours(caplog: pytest.LogCaptureFixture) -> str:
    """What her own code logged; the HTTP client's logger is silent in production (`ashley.logs`)."""
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("ashley"))


def cameras() -> RoutedCameras:
    got = services.get(Cameras)
    assert isinstance(got, RoutedCameras)
    return got


def test_the_kind_serves_cameras_beside_printing_and_stock_and_offers_its_printers_for_the_setting() -> None:
    assert BAMBUDDY.ports == {"printing", "stock", "camera"}
    assert [k.name for k in services.get(ConnectionKinds).of_port("camera")] == ["home_assistant", "bambuddy"]
    (setting,) = BAMBUDDY.settings
    assert setting.key == "look_cameras" and setting.decides == "read" and setting.field == EntityList(("printer",))


@sync
async def test_the_catalogue_offers_each_printer_by_the_id_the_setting_stores(fake: FakeBambuddy) -> None:
    assert BAMBUDDY.catalogue is not None
    (opened,) = await _opened()
    got = await BAMBUDDY.catalogue(opened)
    assert [(e.id, e.name, e.domain) for e in got.entities] == [(SHED, "Shed X1C", "printer"),
                                                                 (LOFT, "Loft P1S", "printer")]


@sync
async def test_with_nothing_named_she_has_no_printer_cameras_and_a_named_one_is_titled_as_bambuddy_names_it(
        fake: FakeBambuddy) -> None:
    services.register(SettingsReader, Settings({1: {}}))
    assert (await cameras().roster(HOME)).cameras == ()
    services.register(SettingsReader, Settings({1: named(SHED, "printer.99")}))
    got = await cameras().roster(HOME)
    assert [(c.id, c.title, c.source) for c in got.cameras] == [(SHED, "Shed X1C", NAME)]


@sync
async def test_a_still_is_bambuddys_snapshot_taken_with_a_token_minted_for_that_look(fake: FakeBambuddy) -> None:
    services.register(SettingsReader, Settings({1: named(SHED)}))
    got = await cameras().look(HOME, SHED)
    assert got.data == JPEG and got.media_type == "image/jpeg" and got.taken is not None
    assert [p for p, _, _ in fake.seen if "camera" in p] == ["/api/v1/printers/camera/stream-token",
                                                              "/api/v1/printers/1/camera/snapshot"]
    assert {k for _, _, k in fake.seen} == {KEY}
    await cameras().look(HOME, SHED)
    assert len(fake.minted) == 2


@sync
async def test_a_printer_not_named_is_never_asked_for_a_picture(fake: FakeBambuddy) -> None:
    services.register(SettingsReader, Settings({1: named(SHED)}))
    with pytest.raises(NoSuchCamera):
        await cameras().look(HOME, LOFT)
    assert not [p for p, _, _ in fake.seen if "snapshot" in p or "stream-token" in p]


@sync
@pytest.mark.parametrize(("fault", "reason"), [("dark", "unreachable"), ("forbidden", "refused")])
async def test_a_printer_that_gives_no_picture_or_a_key_without_camera_permission_is_a_failed_look(
        fake: FakeBambuddy, fault: str, reason: str) -> None:
    services.register(SettingsReader, Settings({1: named(SHED)}))
    if fault == "dark":
        fake.dark.add(1)
    else:
        fake.forbidden.add("/api/v1/printers/camera/stream-token")
    with pytest.raises(CamerasFailed) as got:
        await cameras().look(HOME, SHED)
    assert got.value.reason == reason


@sync
async def test_a_printers_recordings_are_its_archives_with_a_timelapse_titled_as_bambuddy_names_them(
        fake: FakeBambuddy) -> None:
    services.register(SettingsReader, Settings({1: named(SHED)}))
    got = await cameras().recordings(HOME, SHED)
    assert [(r.id, r.camera_id, r.title) for r in got] == [("31", SHED, "Benchy"), ("29", SHED, "plate-29.gcode.3mf")]


@sync
async def test_a_recordings_picture_is_the_middle_frame_and_another_printers_recording_is_not_found(
        fake: FakeBambuddy) -> None:
    services.register(SettingsReader, Settings({1: named(SHED)}))
    got = await cameras().look_recording(HOME, SHED, "31")
    assert (got.data, got.media_type, got.taken, got.title) == (MIDDLE, "image/jpeg", None, "Benchy")
    assert (await cameras().look_recording(HOME, SHED, "29")).data == LAST
    for wrong in ("40", "30", "999", "x"):
        with pytest.raises(NoSuchRecording):
            await cameras().look_recording(HOME, SHED, wrong)


@sync
async def test_a_printer_has_no_live_feed_to_pass_on(fake: FakeBambuddy) -> None:
    source, (opened,) = BambuddyCameras(), await _opened()
    shed = Camera(SHED, "Shed X1C", NAME, opened.connection.id)
    with pytest.raises(NoLiveFeed):
        await source.live_config(opened, shed)
    with pytest.raises(NoLiveFeed):
        async with source.live(opened, shed, "offer"):
            pass
    with pytest.raises(NoLiveFeed):
        await source.live_candidate(opened, shed, "s", Candidate("c", None, None))


def two_sources() -> MemoryHouse:
    house = MemoryHouse()
    house.things = [state(PORCH, "Porch", "idle")]
    house.stills = {PORCH: Snapshot(noise((64, 48)), "image/png")}
    connections = held(HOME)
    connections.connect(HOME, "http://ha.test", "k", ha.NAME)
    services.register(Connections, connections)
    services.register(Homes, AnyHousehold(house))
    services.register(Cameras, RoutedCameras({ha.NAME: ha.HaCameras(), NAME: BambuddyCameras()}, 3))
    return house


@sync
async def test_two_sources_list_together_each_look_goes_to_the_source_that_holds_it_and_neither_list_grants_the_others(
        fake: FakeBambuddy) -> None:
    two_sources()
    kinds = await _ids()
    services.register(SettingsReader, Settings({kinds[NAME]: named(SHED, PORCH)}, named(PORCH, SHED)))
    got = await cameras().roster(HOME)
    assert [(c.id, c.source) for c in got.cameras] == [(PORCH, ha.NAME), (SHED, NAME)]
    assert len({c.id for c in got.cameras}) == 2 and got.unread == ()
    assert (await cameras().look(HOME, PORCH)).media_type == "image/png" and not fake.minted
    assert (await cameras().look(HOME, SHED)).media_type == "image/jpeg" and len(fake.minted) == 1


@sync
async def test_a_bambuddy_that_is_down_leaves_the_other_sources_cameras_and_is_named_unread(fake: FakeBambuddy) -> None:
    two_sources()
    kinds = await _ids()
    services.register(SettingsReader, Settings({kinds[NAME]: named(SHED)}, named(PORCH)))
    services.register(Bambuddy, FakeBambuddy(status=500).client())
    got = await cameras().roster(HOME)
    assert [c.id for c in got.cameras] == [PORCH] and got.unread == (NAME,)


@sync
async def test_a_list_on_the_house_connection_grants_nothing_on_bambuddy_and_the_reverse(fake: FakeBambuddy) -> None:
    two_sources()
    kinds = await _ids()
    services.register(SettingsReader, Settings({kinds[NAME]: {}}, named(SHED)))
    assert (await cameras().roster(HOME)).cameras == ()
    services.register(SettingsReader, Settings({kinds[NAME]: named(PORCH)}))
    assert (await cameras().roster(HOME)).cameras == ()


@sync
async def test_settings_that_cannot_be_read_leave_the_source_unread_not_empty(fake: FakeBambuddy) -> None:
    services.register(SettingsReader, Settings({1: named(SHED)}, down=True))
    got = await cameras().roster(HOME)
    assert got.cameras == () and got.unread == (NAME,)


@sync
async def test_the_log_names_ids_and_counts_never_a_printer_a_title_a_token_or_a_byte(
        fake: FakeBambuddy, caplog: pytest.LogCaptureFixture) -> None:
    services.register(SettingsReader, Settings({1: named(SHED)}))
    with caplog.at_level(logging.DEBUG, logger="ashley"):
        await cameras().roster(HOME)
        await cameras().look(HOME, SHED)
        await cameras().recordings(HOME, SHED)
        await cameras().look_recording(HOME, SHED, "31")
    text = _ours(caplog)
    assert "bambuddy.cameras" in text and "camera.look" in text and "camera.recordings" in text
    for secret in ("Shed X1C", "Loft P1S", "Benchy", "token-0", "front", KEY):
        assert secret not in text


@sync
async def test_a_page_that_is_not_a_picture_is_not_bambuddy_and_the_token_is_in_no_logged_path(
        caplog: pytest.LogCaptureFixture) -> None:
    def html(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=b"<html>", headers={"content-type": "text/html"})

    client = HttpBambuddy(httpx2.AsyncClient(transport=httpx2.MockTransport(html)), 5, 5)
    with caplog.at_level(logging.DEBUG, logger="ashley"), pytest.raises(BambuddyFailed) as got:
        await client.fetch(BASE, KEY, "/api/v1/printers/1/camera/snapshot", {"token": "secret-token"})
    assert got.value.reason == "not_bambuddy" and "secret-token" not in _ours(caplog) and "bambuddy.fetch" in _ours(caplog)


async def _opened() -> tuple[Opened, ...]:
    return await ports.opened_all(services.get(Connections), "camera", HOME)


async def _ids() -> dict[str, int]:
    """The id of each camera connection the household holds, by kind."""
    return {o.connection.kind: o.connection.id for o in await _opened()}
