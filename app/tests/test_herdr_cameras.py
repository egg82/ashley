"""A bench machine's webcams behind the Cameras port, over a fake bridge: one camera per webcam the bridge lists, listed
and looked through only when that herdr connection's `look_cameras` names it, titled with the connection's label and the
device name, a still taken through the bridge only when asked, two machines with the same camera in the same port staying
two cameras, a bridge older than 0.6.0 meaning none, and no name or byte in a log. The household reads the cameras of every
person's bridge."""

import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.cameras.cameras import Cameras
from ashley.cameras.model import Camera, CamerasFailed, Candidate, NoLiveFeed, NoSuchCamera
from ashley.cameras.routed import RoutedCameras
from ashley.connections.connections import Connections, ConnectionsUnavailable
from ashley.connections.kinds import CatalogueUnavailable, ConnectionKinds
from ashley.connections.model import Connection, Opened
from ashley.connections.settings import EntityList, SettingValue, SettingValues
from ashley.connections.settings_read import NullSettingsReader, SettingsReader, StoredSettings
from ashley.herdr import cameras as herdr_cameras
from ashley.herdr.bridge import Bridge, NullBridge
from ashley.herdr.cameras import NAME, HerdrCameras, camera_id
from ashley.herdr.http_bridge import HttpBridge
from ashley.herdr.kind import HERDR
from ashley.herdr.config import load
from ashley.herdr.model import Access, BridgeCamera, BridgeFailed, Reason
from ashley.herdr.transport import ClientCertificate
from ashley.herdr.wire import cameras as parse_cameras
from ashley.wiring import CONNECTION_KINDS
from files_support import sync
from money_support import EPOCH, HeldConnections

HOME, ME, OTHER = 1, 7, 8
JPEG = b"\xff\xd8\xff\xe0made-up-frame"
BENCH, LAPTOP = 1, 2
DESK = BridgeCamera("0abc_1234_1_2", "Test Cam A")
SAME_PORT = BridgeCamera("0abc_1234_1_2", "Test Cam A")
PIN = "0" * 64


@dataclass
class Bridges(NullBridge):
    """Each bridge by origin: its cameras, or the failure it answers the list with."""

    listed: dict[str, tuple[BridgeCamera, ...] | Reason] = field(default_factory=dict[str, tuple[BridgeCamera, ...] | Reason])
    stills: dict[str, bytes | Reason] = field(default_factory=dict[str, bytes | Reason])
    asked: list[tuple[str, str, int]] = field(default_factory=list[tuple[str, str, int]])
    people: list[int] = field(default_factory=list[int])

    async def cameras(self, access: Access) -> tuple[BridgeCamera, ...]:
        self.people.append(access.person)
        got = self.listed[access.origin]
        if isinstance(got, str):
            raise BridgeFailed(got)
        return got

    async def camera_still(self, access: Access, camera_id: str, max_bytes: int) -> bytes:
        self.asked.append((access.origin, camera_id, max_bytes))
        got = self.stills[access.origin]
        if isinstance(got, str):
            raise BridgeFailed(got)
        return got


class Settings(NullSettingsReader):
    def __init__(self, by_connection: Mapping[int, SettingValues], down: bool = False) -> None:
        self.by_connection = by_connection
        self.down = down

    async def stored(self, connection_id: int, household_id: int) -> StoredSettings:
        if self.down:
            raise ConnectionsUnavailable("down")
        return StoredSettings(1, dict(self.by_connection.get(connection_id, {})), None, None)


def named(*ids: str) -> dict[str, SettingValue]:
    return {"look_cameras": list(ids)}


def add(held: HeldConnections, number: int, label: str, person: int = ME) -> None:
    connection = Connection(number, HOME, "herdr", f"https://{label or 'bench'}.test:7843#sha256={PIN}", person, EPOCH,
                            EPOCH, person, label)
    held.held[(HOME, f"herdr:{person}:{number}")] = Opened(connection, "tok")


@pytest.fixture
def bridges() -> Iterator[Bridges]:
    held = HeldConnections()
    add(held, BENCH, "workbench")
    found = Bridges({"https://workbench.test:7843": (DESK, BridgeCamera("0def_5678_1_4", "Test Cam B"))},
                    {"https://workbench.test:7843": JPEG})
    services.register(Connections, held)
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))
    services.register(Bridge, found)
    services.register(SettingsReader, Settings({BENCH: named(camera_id(BENCH, DESK.id))}))
    services.register(Cameras, RoutedCameras({NAME: HerdrCameras()}, 3))
    yield found
    for service in (Connections, Bridge, ConnectionKinds, SettingsReader, Cameras):
        services.unregister(service)


def cameras() -> RoutedCameras:
    got = services.get(Cameras)
    assert isinstance(got, RoutedCameras)
    return got


def test_the_kind_serves_cameras_beside_herdr_and_offers_the_bridges_webcams_for_the_setting() -> None:
    assert HERDR.ports == {"herdr", "camera"}
    (setting,) = HERDR.settings
    assert setting.key == "look_cameras" and setting.decides == "read" and setting.field == EntityList(("webcam",))
    assert [k.name for k in ConnectionKinds(CONNECTION_KINDS).of_port("camera")] == ["home_assistant", "bambuddy", "herdr"]


@sync
async def test_the_catalogue_offers_each_webcam_by_the_id_the_setting_stores(bridges: Bridges) -> None:
    assert HERDR.catalogue is not None
    (opened,) = [o for o in (await services.get(Connections).opened(BENCH, HOME, ME),) if o]
    got = await HERDR.catalogue(opened)
    assert [(e.id, e.name, e.domain) for e in got.entities] == [("webcam.1_0abc_1234_1_2", "Test Cam A", "webcam"),
                                                                 ("webcam.1_0def_5678_1_4", "Test Cam B", "webcam")]
    assert bridges.people == [ME]
    bridges.listed["https://workbench.test:7843"] = "not_found"
    assert (await HERDR.catalogue(opened)).entities == ()
    bridges.listed["https://workbench.test:7843"] = "herdr_unavailable"
    with pytest.raises(CatalogueUnavailable):
        await HERDR.catalogue(opened)


@sync
async def test_with_nothing_named_she_has_no_webcams_and_a_named_one_is_titled_with_the_label_and_the_device_name(
        bridges: Bridges) -> None:
    services.register(SettingsReader, Settings({}))
    assert (await cameras().roster(HOME)).cameras == ()
    services.register(SettingsReader, Settings({BENCH: named(camera_id(BENCH, DESK.id), "webcam.1_0abc_1234_9_9")}))
    got = await cameras().roster(HOME)
    assert [(c.id, c.title, c.source, c.connection_id) for c in got.cameras] == [
        ("webcam.1_0abc_1234_1_2", "workbench: Test Cam A", NAME, BENCH)]


@sync
async def test_a_still_is_asked_of_the_bridge_by_its_own_id_only_when_looked_through_and_never_for_an_unnamed_camera(
        bridges: Bridges) -> None:
    got = await cameras().look(HOME, camera_id(BENCH, DESK.id))
    assert got.data == JPEG and got.media_type == "image/jpeg" and got.taken is not None
    assert bridges.asked == [("https://workbench.test:7843", "0abc_1234_1_2", herdr_cameras.STILL_MAX_BYTES)]
    with pytest.raises(NoSuchCamera):
        await cameras().look(HOME, "webcam.1_0def_5678_1_4")
    assert len(bridges.asked) == 1


@sync
async def test_the_listing_alone_takes_no_picture(bridges: Bridges) -> None:
    await cameras().roster(HOME)
    assert bridges.asked == []


@sync
@pytest.mark.parametrize(("failure", "reason"), [
    ("camera_busy", "unreachable"), ("camera_failed", "unreachable"), ("herdr_unavailable", "unreachable"),
    ("bad_token", "refused"), ("ffmpeg_missing", "unrecognised"), ("too_large", "unrecognised")])
async def test_a_still_the_bridge_cannot_take_is_a_failed_look_with_its_reason(
        bridges: Bridges, failure: Reason, reason: str) -> None:
    bridges.stills["https://workbench.test:7843"] = failure
    with pytest.raises(CamerasFailed) as got:
        await cameras().look(HOME, camera_id(BENCH, DESK.id))
    assert got.value.reason == reason


@sync
async def test_a_camera_the_bridge_no_longer_lists_gives_no_still(bridges: Bridges) -> None:
    bridges.stills["https://workbench.test:7843"] = "not_found"
    source = HerdrCameras()
    (opened,) = [o for o in (await services.get(Connections).opened(BENCH, HOME, ME),) if o]
    assert await source.still(opened, Camera(camera_id(BENCH, DESK.id), "x", NAME, BENCH)) is None


@sync
async def test_a_bridge_older_than_the_cameras_means_none_and_one_that_is_down_is_unread_not_empty(
        bridges: Bridges) -> None:
    bridges.listed["https://workbench.test:7843"] = "not_found"
    got = await cameras().roster(HOME)
    assert got.cameras == () and got.unread == ()
    bridges.listed["https://workbench.test:7843"] = "herdr_unavailable"
    got = await cameras().roster(HOME)
    assert got.cameras == () and got.unread == (NAME,)


@sync
async def test_settings_that_cannot_be_read_leave_the_source_unread_not_empty(bridges: Bridges) -> None:
    services.register(SettingsReader, Settings({BENCH: named(camera_id(BENCH, DESK.id))}, down=True))
    got = await cameras().roster(HOME)
    assert got.cameras == () and got.unread == (NAME,)


@sync
async def test_two_machines_with_the_same_camera_in_the_same_port_are_two_cameras_each_looked_through_its_own_bridge(
        bridges: Bridges) -> None:
    held = HeldConnections()
    add(held, BENCH, "workbench")
    add(held, LAPTOP, "laptop")
    services.register(Connections, held)
    bridges.listed["https://laptop.test:7843"] = (SAME_PORT,)
    bridges.stills["https://laptop.test:7843"] = b"\xff\xd8laptop"
    services.register(SettingsReader, Settings({BENCH: named(camera_id(BENCH, DESK.id)),
                                                LAPTOP: named(camera_id(LAPTOP, SAME_PORT.id))}))
    got = await cameras().roster(HOME)
    assert [(c.id, c.title) for c in got.cameras] == [("webcam.1_0abc_1234_1_2", "workbench: Test Cam A"),
                                                       ("webcam.2_0abc_1234_1_2", "laptop: Test Cam A")]
    assert (await cameras().look(HOME, "webcam.2_0abc_1234_1_2")).data == b"\xff\xd8laptop"
    assert bridges.asked[-1][0] == "https://laptop.test:7843"


@sync
async def test_the_household_reads_the_bridges_of_every_person_each_as_its_own_person(bridges: Bridges) -> None:
    held = HeldConnections()
    add(held, BENCH, "workbench", ME)
    add(held, LAPTOP, "laptop", OTHER)
    services.register(Connections, held)
    bridges.listed["https://laptop.test:7843"] = (BridgeCamera("0aaa_0001_1_1", "Test Cam C"),)
    services.register(SettingsReader, Settings({LAPTOP: named("webcam.2_0aaa_0001_1_1")}))
    got = await cameras().roster(HOME)
    assert [c.id for c in got.cameras] == ["webcam.2_0aaa_0001_1_1"]
    assert sorted(bridges.people) == [ME, OTHER]


@sync
async def test_a_bridge_has_no_live_feed_to_pass_on(bridges: Bridges) -> None:
    (opened,) = [o for o in (await services.get(Connections).opened(BENCH, HOME, ME),) if o]
    source, desk = HerdrCameras(), Camera(camera_id(BENCH, DESK.id), "x", NAME, BENCH)
    with pytest.raises(NoLiveFeed):
        await source.live_config(opened, desk)
    with pytest.raises(NoLiveFeed):
        async with source.live(opened, desk, "offer"):
            pass
    with pytest.raises(NoLiveFeed):
        await source.live_candidate(opened, desk, "s", Candidate("c", None, None))
    assert await source.recordings(opened, desk) == () and await source.recording_still(opened, desk, "1") is None


@sync
async def test_the_log_names_ids_and_counts_never_a_device_a_label_or_a_byte(
        bridges: Bridges, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="ashley"):
        await cameras().roster(HOME)
        await cameras().look(HOME, camera_id(BENCH, DESK.id))
    text = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("ashley"))
    assert "herdr.cameras" in text and "camera.look" in text
    for secret in ("Test Cam", "workbench", "0abc_1234", "front", "tok"):
        assert secret not in text


def test_the_wire_body_of_the_list_parses_and_anything_else_is_unexpected() -> None:
    assert parse_cameras(b'{"cameras": [{"id": "0abc_1234_1_2", "name": "Test Cam A", "extra": 1}]}') == (DESK,)
    for bad in (b"{}", b'{"cameras": [{"id": 1, "name": "x"}]}', b"nope"):
        with pytest.raises(BridgeFailed) as got:
            parse_cameras(bad)
        assert got.value.reason == "unexpected"


@sync
async def test_an_id_that_is_not_one_the_bridge_made_never_leaves_the_app() -> None:
    bridge = HttpBridge(ClientCertificate("/nope", "/nope"), load())
    access = Access.of(f"https://x.test:7843#sha256={PIN}", "t", ME)
    for bad in ("../x", "0abc_1234", "0ABC_1234_1", "0abc_1234_1/still"):
        with pytest.raises(BridgeFailed) as got:
            await bridge.camera_still(access, bad, 10)
        assert got.value.reason == "not_found"
