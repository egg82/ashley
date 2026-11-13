"""`GET /api/live` through the real app with a fake Live: the viewer is the signed-in person, each event is one `data:`
line of `LiveEvent`, heartbeats are comment lines, the stream ends after `stream_s`, no session is 401, no feed is 503,
and nothing but ids reaches the log."""

from collections.abc import Generator
from dataclasses import dataclass, field, replace

import pytest
from ashley import services
from ashley.api import live as live_route
from ashley.api.live_models import LiveEvent, LiveResync, LiveState, LiveTurn
from ashley.api.models import ErrorResponse
from ashley.api.person import person_signed_in
from ashley.live.events import HerState, Shown, ThreadTurn, Viewer
from ashley.live.fanout import RESYNC
from ashley.live.live import Live
from ashley.live.screens import NullScreens, OpenScreen, Screens
from ashley.main import create_app
from ashley.settings import Settings
from ashley.signin.model import SignedIn
from fastapi.testclient import TestClient
from live_support import FakeLive
from respond_support import ALANA

PUBLIC = "https://ashley.test"
THINKING = HerState(Shown(ALANA.household_id, None), "a1b2", "thinking", 180.0)
TURN = ThreadTurn(Shown(ALANA.household_id, ALANA.id), f"person:{ALANA.id}:web")


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_route, "CONFIG", replace(live_route.CONFIG, heartbeat_s=0.05, stream_s=0.2))


def _client(live: Live | None, signed_in: bool = True) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    if live is None:
        services.unregister(Live)
    else:
        services.register(Live, live)
    if signed_in:
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, ALANA)
    return TestClient(app, base_url=PUBLIC)


@pytest.fixture
def fake() -> Generator[FakeLive]:
    yield FakeLive((THINKING, TURN, RESYNC))
    services.unregister(Live)


def read(client: TestClient) -> tuple[dict[str, str], list[str]]:
    with client.stream("GET", "/api/live") as response:
        assert response.status_code == 200
        return dict(response.headers), list(response.iter_lines())


def test_the_stream_is_the_signed_in_persons_events_as_data_lines(fake: FakeLive) -> None:
    headers, lines = read(_client(fake))
    assert headers["content-type"].startswith("text/event-stream") and headers["cache-control"] == "no-cache"
    assert fake.viewers == [Viewer(ALANA.household_id, ALANA.id)]
    data = [LiveEvent.model_validate_json(line.removeprefix("data: ")).root for line in lines if line.startswith("data:")]
    assert data == [LiveState(type="state", turn="a1b2", state="thinking", at_most_s=180.0),
                    LiveTurn(type="turn", thread=f"person:{ALANA.id}:web"), LiveResync(type="resync")]


def test_heartbeats_are_comments_and_the_stream_ends_on_its_own(fake: FakeLive) -> None:
    _, lines = read(_client(fake))
    assert lines[0] == ":" or lines[0] == ": "
    assert sum(line.startswith(":") for line in lines) >= 3
    assert all(line == "" or line.startswith((":", "data: ")) for line in lines)
    assert fake.fanout.deliver(THINKING) == 0


def test_no_session_is_401(fake: FakeLive) -> None:
    response = _client(fake, signed_in=False).get("/api/live")
    assert response.status_code == 401 and ErrorResponse.model_validate(response.json()).code == "unauthorized"
    assert fake.viewers == []


def test_no_feed_is_503_so_the_screen_looks_for_itself() -> None:
    response = _client(None).get("/api/live")
    assert response.status_code == 503 and ErrorResponse.model_validate(response.json()).code == "unavailable"


def test_only_ids_are_logged(fake: FakeLive, capsys: pytest.CaptureFixture[str]) -> None:
    read(_client(fake))
    out = capsys.readouterr().out
    assert "event=live.opened" in out and f"person={ALANA.id}" in out and "event=live.closed" in out
    assert "a1b2" not in out and "web" not in out


@dataclass
class RecordingScreens(Screens):
    """The record of open screens, in memory: `calls` is every call made, in order."""

    calls: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    tokens: list[str | None] = field(default_factory=list[str | None])
    reports: list[tuple[str, int, str, bool]] = field(default_factory=list[tuple[str, int, str, bool]])

    async def opened(self, household_id: int, person_id: int, token: str | None = None) -> int:
        self.calls.append(("opened", person_id))
        self.tokens.append(token)
        return 41

    async def device_opened(self, household_id: int, device_id: int, token: str | None = None) -> int:
        self.calls.append(("device_opened", device_id))
        self.tokens.append(token)
        return 42

    async def person_visible(self, person_id: int, token: str, visible: bool) -> None:
        self.reports.append(("person", person_id, token, visible))

    async def device_visible(self, device_id: int, token: str, visible: bool) -> None:
        self.reports.append(("device", device_id, token, visible))

    async def open_screens(self, household_id: int, within_s: float) -> tuple[OpenScreen, ...]:
        return ()

    async def beat(self, screen_id: int) -> None:
        self.calls.append(("beat", screen_id))

    async def closed(self, screen_id: int) -> None:
        self.calls.append(("closed", screen_id))

    async def looking(self, person_id: int, within_s: float) -> bool:
        return any(c == ("opened", person_id) for c in self.calls) and ("closed", 41) not in self.calls

    async def showing(self, device_id: int, within_s: float) -> bool:
        return any(c == ("device_opened", device_id) for c in self.calls) and ("closed", 42) not in self.calls


def test_a_persons_open_stream_is_recorded_refreshed_while_it_lives_and_removed_when_it_ends(fake: FakeLive) -> None:
    screens = RecordingScreens()
    client = _client(fake)
    services.register(Screens, screens)
    read(client)
    kinds = [kind for kind, _ in screens.calls]
    assert screens.calls[0] == ("opened", ALANA.id) and kinds.count("opened") == 1
    assert kinds.count("beat") >= 2 and {n for kind, n in screens.calls if kind == "beat"} == {41}
    assert screens.calls[-1] == ("closed", 41) and kinds.count("closed") == 1


def test_a_record_that_cannot_be_written_never_ends_the_stream(fake: FakeLive) -> None:
    client = _client(fake)
    services.register(Screens, NullScreens())
    _, lines = read(client)
    assert any(line.startswith("data: ") for line in lines)


TOKEN = "3f2b8a64-0c1d-4e57-9a1b-6d5e7f8091a2"


def test_the_feed_opens_its_screen_under_the_pages_token(fake: FakeLive) -> None:
    screens = RecordingScreens()
    client = _client(fake)
    services.register(Screens, screens)
    with client.stream("GET", f"/api/live?screen={TOKEN}") as response:
        list(response.iter_lines())
    assert screens.tokens == [TOKEN]


def test_a_feed_with_a_token_that_is_not_one_is_422(fake: FakeLive) -> None:
    assert _client(fake).get("/api/live?screen=nope").status_code == 422


def test_a_visibility_report_is_the_signed_in_persons_own_whatever_the_body_says(fake: FakeLive) -> None:
    screens = RecordingScreens()
    client = _client(fake)
    services.register(Screens, screens)
    response = client.post("/api/screens/visibility", json={"screen": TOKEN, "visible": False, "person": 99},
                           headers={"origin": PUBLIC})
    assert response.status_code == 204 and response.content == b""
    assert screens.reports == [("person", ALANA.id, TOKEN, False)]


def test_a_visibility_report_needs_a_session_and_a_token(fake: FakeLive) -> None:
    screens = RecordingScreens()
    services.register(Screens, screens)
    body = {"screen": TOKEN, "visible": True}
    assert _client(fake, signed_in=False).post("/api/screens/visibility", json=body,
                                                headers={"origin": PUBLIC}).status_code == 401
    assert _client(fake).post("/api/screens/visibility", json={"screen": "x", "visible": True},
                              headers={"origin": PUBLIC}).status_code == 422
    assert screens.reports == []


def test_a_visibility_report_with_no_record_wired_is_503_and_logs_only_ids(
        fake: FakeLive, capsys: pytest.CaptureFixture[str]) -> None:
    client = _client(fake)
    services.register(Screens, NullScreens())
    response = client.post("/api/screens/visibility", json={"screen": TOKEN, "visible": True},
                           headers={"origin": PUBLIC})
    out = capsys.readouterr().out
    assert response.status_code == 503 and ErrorResponse.model_validate(response.json()).code == "unavailable"
    assert "event=screens.unavailable" in out and TOKEN not in out
