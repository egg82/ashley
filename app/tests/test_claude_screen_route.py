"""`GET /api/claude/sessions/{id}/screen` through the real app over a fake bridge: the signed-in person's own bridge is
read, a live screen comes with its status, a digest and its text, the text is left out when the page already has that
digest, every way the bridge fails is a state rather than an error, the wait before the next ask follows the session,
and the screen never reaches the log."""

import logging
from collections.abc import Generator
from dataclasses import dataclass, field

import pytest
from ashley import services
from ashley.api import claude_screen
from ashley.api.claude_screen import SessionScreen
from ashley.api.person import person_signed_in
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Access, BridgeFailed, Reason, Screen, Session, Status
from ashley.main import create_app
from ashley.people.model import Person
from ashley.settings import Settings
from ashley.wiring import CONNECTION_KINDS
from ashley.signin.model import SignedIn
from bench_jobs_support import BRIDGE_URL, FakeBridge
from fastapi.testclient import TestClient
from money_support import HeldConnections
from respond_support import ALANA, SAM

PUBLIC = "https://ashley.test"
ID = "0a1b2c3d-0000-4000-8000-00000000abcd"
OTHER = "0a1b2c3d-0000-4000-8000-00000000ffff"
TEXT = "● Reading the parser\n  ⎿ 42 lines\nSECRET-SCREEN-WORDS"
CONFIG = claude_screen.CONFIG


@dataclass
class ScreenBridge(FakeBridge):
    """A bridge whose read gives `text` for any session unless `read_refuse` says otherwise, and records who asked."""

    text: str = TEXT
    read_refuse: Reason | None = None
    asked: list[tuple[int, str, int]] = field(default_factory=list[tuple[int, str, int]])

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        self._up()
        self.asked.append((access.person, session_id, lines))
        if self.read_refuse is not None:
            raise BridgeFailed(self.read_refuse)
        return Screen(self.text, True, 4)


def listed(status: Status = "working", session: str = ID) -> dict[str, Session]:
    return {session: Session(session, "fix-parser", "/work/p", status, 9, None)}


@pytest.fixture
def bridge() -> Generator[ScreenBridge]:
    yield ScreenBridge(listed=listed())
    services.unregister(Bridge)
    services.unregister(Connections)


def client(bridge: ScreenBridge, connected: bool = True, down: bool = False, signed_in: bool = True,
           who: Person = ALANA) -> TestClient:
    app = create_app(Settings(database_url="", build_version="test", public_url=PUBLIC))
    held = HeldConnections(down=down)
    if connected:
        held.connect(ALANA.household_id, BRIDGE_URL, "tok", "herdr", ALANA.id)
    services.register(Connections, held)
    services.register(Bridge, bridge)
    services.register(ConnectionKinds, ConnectionKinds(CONNECTION_KINDS))  # the app wires herdr only with a certificate
    if signed_in:
        app.dependency_overrides[person_signed_in] = lambda: SignedIn(1, who)
    return TestClient(app, base_url=PUBLIC)


def screen(c: TestClient, session: str = ID, seen: str | None = None) -> SessionScreen:
    got = c.get(f"/api/claude/sessions/{session}/screen", params={} if seen is None else {"seen": seen})
    assert got.status_code == 200, got.text
    return SessionScreen.model_validate(got.json())


def test_a_live_screen_is_read_from_the_persons_own_bridge(bridge: ScreenBridge) -> None:
    got = screen(client(bridge))
    assert (got.state, got.status, got.text, got.truncated) == ("live", "working", TEXT, True)
    assert got.digest and got.again_ms == int(CONFIG.screen_working_s * 1000)
    assert bridge.asked == [(ALANA.id, ID, CONFIG.screen_lines)]


def test_an_unchanged_screen_comes_back_without_its_text_and_a_changed_one_with_it(bridge: ScreenBridge) -> None:
    c = client(bridge)
    first = screen(c)
    again = screen(c, seen=first.digest)
    assert (again.state, again.digest, again.text) == ("live", first.digest, None)
    bridge.text = TEXT + "\nmore"
    changed = screen(c, seen=first.digest)
    assert changed.text == TEXT + "\nmore" and changed.digest != first.digest


def test_a_session_that_is_not_working_is_asked_again_later(bridge: ScreenBridge) -> None:
    bridge.listed = listed("idle")
    got = screen(client(bridge))
    assert (got.status, got.again_ms) == ("idle", int(CONFIG.screen_still_s * 1000))
    assert CONFIG.screen_still_s > CONFIG.screen_working_s


@pytest.mark.parametrize(("attr", "value", "state"), [
    ("listed", {}, "gone"),
    ("listed", listed(session=OTHER), "gone"),
    ("read_refuse", "not_found", "gone"),
    ("down", True, "unreachable"),
    ("read_refuse", "herdr_unavailable", "unreachable"),
    ("read_refuse", "unconfirmed", "unreachable"),
    ("refuse", "bad_token", "refused"),
    ("refuse", "pin_mismatch", "refused"),
    ("refuse", "wrong_person", "refused"),
    ("refuse", "unexpected", "refused"),
])
def test_each_way_the_bridge_fails_is_a_state_not_an_error(bridge: ScreenBridge, attr: str, value: object,
                                                           state: str) -> None:
    setattr(bridge, attr, value)
    got = screen(client(bridge))
    assert (got.state, got.status, got.text, got.digest) == (state, None, None, None)
    away = state in ("unreachable", "refused")
    assert got.again_ms == int((CONFIG.screen_away_s if away else CONFIG.screen_still_s) * 1000)


def test_a_person_with_no_bridge_or_unreadable_connections(bridge: ScreenBridge) -> None:
    assert screen(client(bridge, connected=False)).state == "not_connected"
    assert screen(client(bridge, down=True)).state == "unreachable"
    assert bridge.asked == []


def test_another_persons_bridge_is_never_read(bridge: ScreenBridge) -> None:
    assert screen(client(bridge, who=SAM)).state == "not_connected" and bridge.asked == []


def test_an_id_that_is_not_a_session_and_no_sign_in_are_refused(bridge: ScreenBridge) -> None:
    assert client(bridge).get("/api/claude/sessions/..%2Fetc/screen").status_code in (404, 422)
    assert client(bridge).get(f"/api/claude/sessions/{ID.upper()}/screen").status_code == 422
    assert client(bridge, signed_in=False).get(f"/api/claude/sessions/{ID}/screen").status_code == 401
    assert bridge.asked == []


def test_the_screen_never_reaches_the_log(bridge: ScreenBridge, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    c = client(bridge)
    screen(c)
    bridge.read_refuse = "herdr_unavailable"
    screen(c)
    events = [r for r in caplog.records if r.getMessage() == "claude.screen"]
    assert len(events) == 1 and getattr(events[0], "fields") == {"state": "unreachable", "reason": "herdr_unavailable",
                                                                 "duration_ms": getattr(events[0], "fields")["duration_ms"]}
    assert not any("SECRET-SCREEN-WORDS" in (r.getMessage() + str(getattr(r, "fields", ""))) for r in caplog.records)
