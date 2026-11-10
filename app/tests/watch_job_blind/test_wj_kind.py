"""The claude_session kind: one Bridge.sessions call per person, each watch keeping only its target; and the Null kind."""

from typing import Any

from ashley import services
from ashley.connections.connections import Connections
from ashley.herdr.bridge import Bridge
from ashley.watches.kinds import Kind
from ashley.herdr.model import Access, BridgeFailed, Reason, OutFile, Screen, Session, SessionList, Status
from money_support import HeldConnections
from watch_job_blind_support import (BASE, HOUSEHOLD, OTHER_PERSON, PERSON, SLUGS, ClaudeSession, NullKind,
                                     ReadFailed, run, watch_of)


def session(sid: str, status: Status = "working", seq: int = 1) -> Session:
    return Session(sid, "a label", "/some/dir", status, seq, None)


class FakeBridge(Bridge):
    def __init__(self, *sessions: Session) -> None:
        self.sessions_: tuple[Session, ...] = sessions
        self.accesses: list[Access] = []
        self.fail: BridgeFailed | None = None

    async def sessions(self, access: Access) -> SessionList:
        self.accesses.append(access)
        if self.fail is not None:
            raise self.fail
        return SessionList(self.sessions_, None)

    async def whoami(self, access: Access) -> Any:
        raise AssertionError("not used")

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        raise AssertionError("not used")

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        raise AssertionError("not used")

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        raise AssertionError("not used")

    async def close(self, access: Access, session_id: str) -> None:
        raise AssertionError("not used")

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        raise AssertionError("not used")

    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        raise AssertionError("not used")

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        raise AssertionError("not used")


def world(*sessions: Session, connected: bool = True) -> FakeBridge:
    bridge, connections = FakeBridge(*sessions), HeldConnections()
    if connected:
        connections.connect(HOUSEHOLD, BASE, "token", "herdr", PERSON)
    services.register(Bridge, bridge)
    services.register(Connections, connections)
    return bridge


async def reading(kind: Kind, watches: Any) -> Any:
    return await kind.read(watches)


def group(*targets: str, person: int = PERSON) -> tuple[Any, ...]:
    watches = tuple(watch_of(i + 1, target=t, person_id=person) for i, t in enumerate(targets))
    return watches


def test_one_bridge_call_serves_every_watch_of_the_person_and_each_keeps_only_its_target() -> None:
    bridge = world(session("a", "done", 42), session("b", "blocked", 7), session("c"))

    async def go() -> None:
        got = await reading(ClaudeSession(), group("a", "b"))
        assert len(bridge.accesses) == 1 and bridge.accesses[0].person == PERSON
        assert set(got) == {1, 2}
        assert set(got[1]) == {"a"} and set(got[2]) == {"b"}
        assert got[1]["a"]["status"] == "done" and got[1]["a"]["seq"] == 42
        assert got[2]["b"]["status"] == "blocked" and got[2]["b"]["seq"] == 7
    run(go())


def test_a_target_missing_from_a_successful_read_is_gone_not_failed() -> None:
    world(session("a"))

    async def go() -> None:
        got = await reading(ClaudeSession(), group("a", "closed"))
        assert dict(got[2]) == {} and not isinstance(got[2], ReadFailed) and "a" in got[1]
    run(go())


def test_an_empty_session_list_is_every_target_gone() -> None:
    world()

    async def go() -> None:
        got = await reading(ClaudeSession(), group("a", "b"))
        assert [dict(got[i]) for i in (1, 2)] == [{}, {}]
    run(go())


def test_an_unreachable_bridge_fails_every_watch_with_unreachable() -> None:
    bridge = world(session("a"))
    bridge.fail = BridgeFailed("herdr_unavailable")

    async def go() -> None:
        got = await reading(ClaudeSession(), group("a", "b"))
        assert len(bridge.accesses) == 1 and set(got) == {1, 2}
        assert all(isinstance(r, ReadFailed) and r.reason == "unreachable" for r in got.values())
    run(go())


def test_a_person_with_no_bridge_connection_fails_not_connected_and_the_bridge_is_not_asked() -> None:
    bridge = world(session("a"), connected=False)

    async def go() -> None:
        got = await reading(ClaudeSession(), group("a"))
        assert isinstance(got[1], ReadFailed) and got[1].reason == "not_connected" and bridge.accesses == []
    run(go())


def test_the_connection_of_another_person_is_not_used() -> None:
    bridge = world(session("a"))

    async def go() -> None:
        got = await reading(ClaudeSession(), group("a", person=OTHER_PERSON))
        assert isinstance(got[1], ReadFailed) and got[1].reason == "not_connected" and bridge.accesses == []
    run(go())


def test_any_other_bridge_refusal_is_a_failure_from_the_closed_list_never_gone() -> None:
    bridge = world(session("a"))

    async def go() -> None:
        reasons: tuple[Reason, ...] = ("bad_token", "wrong_person", "pin_mismatch", "unexpected", "busy")
        for reason in reasons:
            bridge.fail = BridgeFailed(reason)
            got = await reading(ClaudeSession(), group("a"))
            assert isinstance(got[1], ReadFailed) and got[1].reason in SLUGS, reason
    run(go())


def test_the_bridge_is_asked_with_the_connections_address_and_token() -> None:
    bridge = world(session("a"))

    async def go() -> None:
        await reading(ClaudeSession(), group("a"))
        assert bridge.accesses == [Access.of(BASE, "token", PERSON)]
    run(go())


def test_the_null_kind_fails_every_watch_unknown_kind() -> None:
    async def go() -> None:
        got = await reading(NullKind(), group("a", "b"))
        assert set(got) == {1, 2}
        assert all(isinstance(r, ReadFailed) and r.reason == "unknown_kind" for r in got.values())
    run(go())
