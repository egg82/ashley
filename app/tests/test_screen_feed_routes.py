"""A camera's live feed on a screen through the real app, for the kiosk (`/api/kiosk/feed`) and a person's page
(`/api/screens/feed`), over the camera port and an in-memory open-screens record: a screen reads back only its own feed and
never the camera's id; its offer is relayed to the camera and the camera's session, answer and candidates stream back as
`data:` lines, the camera's feed closing when the page's stream does; its candidates are relayed; a screen that shows no feed,
whose time is up, whose camera is off the household's list or whose token is another's is refused, and a camera with no
live video ends the stream with an `error` signal; a swipe takes it off that screen; and no log holds an offer, an answer, a
candidate or a camera."""

import json
import time
from collections.abc import Generator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from ashley import services
from ashley.api import screen_feed
from ashley.api.kiosk_device import kiosk_signed_in
from ashley.api.models import ErrorResponse
from ashley.api.person import person_signed_in
from ashley.api.screen_feed_models import FeedSignal, ScreenFeedRead
from ashley.cameras.cameras import Cameras
from ashley.cameras.model import Candidate, IceServer, LiveAnswer, LiveCandidate, LiveConfig, LiveSession
from ashley.cameras.routed import RoutedCameras
from ashley.connections.connections import Connections
from ashley.connections.settings_read import SettingsReader
from ashley.home_assistant.cameras import NAME, HaCameras
from ashley.home_assistant.homes import Homes
from ashley.live.live import Live
from ashley.live.screens import OpenScreen, ScreenFeed, Screens
from ashley.main import create_app
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from homes_support import AnyHousehold
from house_double_support import MemoryHouse, state
from money_support import HeldConnections
from respond_support import ALANA, HOME
from test_camera_port import BACK, HALL, PORCH, Settings as ListedCameras
from test_kiosk_routes import DEVICE

PUBLIC = "https://ashley.test"
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
TOKEN = str(uuid4())
OFFER = "v=0\r\no=- 7 7 IN IP4 192.0.2.50\r\nzqOFFERBODY"
ANSWER = "v=0\r\no=- 8 8 IN IP4 192.0.2.51\r\nzqANSWERBODY"
LINE = "candidate:9 1 udp 2113937151 192.0.2.52 50100 typ host zqCANDIDATE"
SCRIPT = [LiveSession("zqsession01"), LiveAnswer(ANSWER), LiveCandidate(Candidate(LINE, "0", 0, None))]


@dataclass
class MemoryScreens(Screens):
    """Open screens in memory: each token's owner (`person`/`device`, id), and the feed it shows."""

    shown: dict[str, tuple[tuple[str, int], ScreenFeed]] = field(default_factory=dict[str, tuple[tuple[str, int], ScreenFeed]])

    async def opened(self, household_id: int, person_id: int, token: str | None = None) -> int:
        return 1

    async def device_opened(self, household_id: int, device_id: int, token: str | None = None) -> int:
        return 1

    async def person_visible(self, person_id: int, token: str, visible: bool) -> None:
        return None

    async def device_visible(self, device_id: int, token: str, visible: bool) -> None:
        return None

    async def open_screens(self, household_id: int, within_s: float) -> tuple[OpenScreen, ...]:
        return ()

    async def beat(self, screen_id: int) -> None:
        return None

    async def closed(self, screen_id: int) -> None:
        return None

    async def looking(self, person_id: int, within_s: float) -> bool:
        return False

    async def showing(self, device_id: int, within_s: float) -> bool:
        return False

    async def feed_of(self, token: str, now: datetime, person_id: int | None = None,
                      device_id: int | None = None) -> ScreenFeed | None:
        held = self.shown.get(token)
        owner = ("person", person_id) if person_id is not None else ("device", device_id or 0)
        return held[1] if held is not None and held[0] == owner and held[1].until > now else None

    async def dismiss_feed(self, token: str, person_id: int | None = None, device_id: int | None = None) -> None:
        self.shown.pop(token, None)


@dataclass
class World:
    house: MemoryHouse
    screens: MemoryScreens
    clock: list[datetime]
    connections: HeldConnections
    settings: ListedCameras


CURRENT: list[World] = []


def wire() -> None:
    """The world's services, registered again after `create_app` has put its own."""
    w = CURRENT[0]
    services.register(Connections, w.connections)
    services.register(Homes, AnyHousehold(w.house))
    services.register(Cameras, RoutedCameras({NAME: HaCameras()}))
    services.register(SettingsReader, w.settings)
    services.register(Screens, w.screens)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Generator[World]:
    house = MemoryHouse()
    house.things = [state(PORCH, "Porch", "idle"), state(HALL, "Hall", "idle"), state(BACK, "Back garden", "idle")]
    house.live_script = list(SCRIPT)
    house.live_cfg = LiveConfig((IceServer(("stun:stun.example.test:3478",), None, None),), "dataSendChannel")
    held = HeldConnections()
    held.connect(HOME.id, "http://ha.test", "k", NAME)
    screens = MemoryScreens()
    clock = [NOW]
    monkeypatch.setattr(screen_feed, "_now", lambda: clock[0])
    monkeypatch.setattr(screen_feed, "CONFIG", replace(screen_feed.CONFIG, heartbeat_s=0.05))
    CURRENT[:] = [World(house, screens, clock, held, ListedCameras())]
    wire()
    yield CURRENT[0]
    for interface in (Connections, Homes, Cameras, SettingsReader, Screens, Live):
        services.unregister(interface)


def showing(w: World, camera: str = PORCH, owner: tuple[str, int] = ("device", DEVICE.id),
            until: datetime = NOW + timedelta(seconds=90)) -> None:
    w.screens.shown[TOKEN] = (owner, ScreenFeed(camera, until))


def kiosk() -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    app.dependency_overrides[kiosk_signed_in] = lambda: DEVICE
    wire()
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


def page() -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    wire()
    return TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})


def signals(client: TestClient, enough: int = 3, body: dict[str, object] | None = None) -> list[object]:
    """The `data:` lines of the offer's stream, read until `enough` have come or it ends."""
    got: list[object] = []
    with client.stream("POST", "/api/kiosk/feed/offer", json={"screen": TOKEN, "offer": OFFER, **(body or {})}) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("data: "):
                got.append(FeedSignal.model_validate_json(line.removeprefix("data: ")).root.model_dump())
                if len(got) == enough:
                    break
    return got


def closed(w: World) -> bool:
    for _ in range(200):
        if w.house.live_closed:
            return True
        time.sleep(0.01)
    return False


def test_a_screen_reads_its_own_feed_with_what_its_browser_needs_and_never_the_cameras_id(world: World) -> None:
    client = kiosk()
    assert ScreenFeedRead.model_validate(client.get("/api/kiosk/feed", params={"screen": TOKEN}).json()).feed is None
    showing(world)
    response = client.get("/api/kiosk/feed", params={"screen": TOKEN})
    got = ScreenFeedRead.model_validate(response.json()).feed
    assert got is not None and got.camera_title == "Porch" and got.remaining_s == 90 and got.data_channel == "dataSendChannel"
    assert [s.urls for s in got.ice_servers] == [["stun:stun.example.test:3478"]]
    assert "zq_porch" not in response.text


def test_a_token_is_its_owners_alone(world: World) -> None:
    showing(world, owner=("device", DEVICE.id + 1))
    assert ScreenFeedRead.model_validate(kiosk().get("/api/kiosk/feed", params={"screen": TOKEN}).json()).feed is None
    assert kiosk().post("/api/kiosk/feed/offer", json={"screen": TOKEN, "offer": OFFER}).status_code == 404
    assert world.house.offers == []
    showing(world, owner=("person", ALANA.id))
    assert ScreenFeedRead.model_validate(page().get("/api/screens/feed", params={"screen": TOKEN}).json()).feed is not None


def test_the_offer_is_relayed_and_the_cameras_signals_stream_back_until_the_page_closes_its_stream(world: World) -> None:
    showing(world)
    got = signals(kiosk())
    assert got == [{"type": "session", "session_id": "zqsession01"}, {"type": "answer", "answer": ANSWER},
                   {"type": "candidate", "candidate": LINE, "sdp_mid": "0", "sdp_m_line_index": 0, "username_fragment": None}]
    assert world.house.offers == [(PORCH, OFFER)] and world.house.live_open == 1
    assert closed(world) and world.house.live_closed == 1


def test_a_persons_page_streams_its_feed_the_same_way(world: World) -> None:
    showing(world, owner=("person", ALANA.id))
    with page().stream("POST", "/api/screens/feed/offer", json={"screen": TOKEN, "offer": OFFER}) as response:
        first = next(line for line in response.iter_lines() if line.startswith("data: "))
    assert json.loads(first.removeprefix("data: ")) == {"type": "session", "session_id": "zqsession01"}
    assert closed(world)


def test_a_quiet_stream_carries_comment_lines_between_signals(world: World) -> None:
    showing(world)
    with kiosk().stream("POST", "/api/kiosk/feed/offer", json={"screen": TOKEN, "offer": OFFER}) as response:
        lines: list[str] = []
        for line in response.iter_lines():
            lines.append(line)
            if sum(x.startswith(":") for x in lines) >= 2:
                break
    assert sum(x.startswith("data: ") for x in lines) == 3


def test_the_browsers_candidates_are_relayed_for_the_session(world: World) -> None:
    showing(world)
    sent = {"screen": TOKEN, "session_id": "zqsession01", "candidate": LINE, "sdp_mid": "0", "sdp_m_line_index": 1}
    assert kiosk().post("/api/kiosk/feed/candidate", json=sent).status_code == 204
    assert world.house.candidates == [(PORCH, "zqsession01", Candidate(LINE, "0", 1, None))]


@pytest.mark.parametrize("path", ["/api/kiosk/feed/offer", "/api/kiosk/feed/candidate"])
def test_a_screen_with_no_feed_or_whose_time_is_up_is_refused_and_the_camera_not_asked(world: World, path: str) -> None:
    body = {"screen": TOKEN, "offer": OFFER} if path.endswith("offer") else {"screen": TOKEN, "session_id": "s", "candidate": LINE}
    assert kiosk().post(path, json=body).status_code == 404
    showing(world)
    world.clock[0] = NOW + timedelta(seconds=90)
    response = kiosk().post(path, json=body)
    assert response.status_code == 404 and ErrorResponse.model_validate(response.json()).code == "not_found"
    assert world.house.offers == [] and world.house.candidates == []


@pytest.mark.parametrize("path", ["/api/kiosk/feed/offer", "/api/kiosk/feed/candidate"])
def test_a_camera_taken_off_the_households_list_is_refused_though_it_was_shown(world: World, path: str) -> None:
    showing(world, BACK)
    body = {"screen": TOKEN, "offer": OFFER} if path.endswith("offer") else {"screen": TOKEN, "session_id": "s", "candidate": LINE}
    assert kiosk().post(path, json=body).status_code == 404
    showing(world, PORCH)
    world.settings = ListedCameras(looks=(HALL,))
    assert kiosk().post(path, json=body).status_code == 404
    assert ScreenFeedRead.model_validate(kiosk().get("/api/kiosk/feed", params={"screen": TOKEN}).json()).feed is None
    assert world.house.offers == [] and world.house.candidates == []


def test_a_camera_with_no_live_video_ends_the_stream_with_an_error_signal(world: World) -> None:
    world.house.no_live = frozenset({PORCH})
    showing(world)
    assert signals(kiosk(), enough=2) == [{"type": "error", "code": "unavailable"}]


def test_a_feed_whose_time_is_nearly_up_ends_its_stream_by_itself_and_closes_the_cameras_feed(world: World) -> None:
    showing(world, until=NOW + timedelta(milliseconds=2))
    signals(kiosk(), enough=99)
    assert closed(world) and world.house.live_closed == 1


def test_a_swipe_takes_the_feed_off_that_screen(world: World) -> None:
    showing(world)
    assert kiosk().delete("/api/kiosk/feed", params={"screen": TOKEN}).status_code == 204
    assert ScreenFeedRead.model_validate(kiosk().get("/api/kiosk/feed", params={"screen": TOKEN}).json()).feed is None


def test_the_house_being_down_is_503_for_a_read_and_an_offer(world: World) -> None:
    showing(world)
    world.house.down = True
    assert kiosk().get("/api/kiosk/feed", params={"screen": TOKEN}).status_code == 503
    assert kiosk().post("/api/kiosk/feed/offer", json={"screen": TOKEN, "offer": OFFER}).status_code == 503


def test_bodies_outside_the_models_are_validation_errors(world: World) -> None:
    showing(world)
    assert kiosk().post("/api/kiosk/feed/offer", json={"screen": "not-a-uuid", "offer": OFFER}).status_code == 422
    assert kiosk().post("/api/kiosk/feed/offer", json={"screen": TOKEN, "offer": ""}).status_code == 422
    assert kiosk().post("/api/kiosk/feed/candidate", json={"screen": TOKEN, "session_id": "s"}).status_code == 422
    assert kiosk().get("/api/kiosk/feed").status_code == 422


def test_no_sign_in_is_401(world: World) -> None:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    client = TestClient(app, base_url=PUBLIC, headers={"origin": PUBLIC})
    assert client.get("/api/kiosk/feed", params={"screen": TOKEN}).status_code == 401
    assert client.get("/api/screens/feed", params={"screen": TOKEN}).status_code == 401


def test_no_log_holds_an_offer_an_answer_a_candidate_or_a_camera(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    showing(world)
    capsys.readouterr()
    signals(kiosk())
    kiosk().post("/api/kiosk/feed/candidate", json={"screen": TOKEN, "session_id": "zqsession01", "candidate": LINE})
    kiosk().get("/api/kiosk/feed", params={"screen": TOKEN})
    out = capsys.readouterr().out
    assert "screen.feed" in out
    for secret in ("zqOFFERBODY", "zqANSWERBODY", "zqCANDIDATE", "192.0.2", "zq_porch", "Porch", "zqsession01", TOKEN):
        assert secret not in out
