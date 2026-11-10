"""`HttpBridge` against the real bridge program (`bridge/herdr`) over real mutual TLS, with the fake `herdr` behind it
that replays answers captured from the real CLI."""

import asyncio
import json
import threading
from collections.abc import Awaitable, Generator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypeVar

import pytest
from ashley import services
from ashley.connections.kinds import Refusal
from ashley.herdr.bridge import Bridge, NullBridge
from ashley.herdr.config import load
from ashley.herdr.http_bridge import HttpBridge
from ashley.herdr.kind import HERDR
from ashley.herdr.model import Access, BridgeFailed
from ashley.herdr.transport import ClientCertificate
from ashley.herdr.wire import sessions
from herdr_bridge.runner import HerdrMissing, HerdrTimeout, Outcome

from herdr_bridge_support import (PERSON, THROWAWAY, TOKEN, FakeHerdr, Issued, Served, ca_with_client, listing, ok,
                                  serving)

T = TypeVar("T")
PANE = "w5H:pK"
READ = ("agent", "read", PANE, "--source", "recent-unwrapped", "--lines", "120")
PROMPT = ("agent", "prompt", PANE, "reply with ok")
START = ("agent", "start", "bridge-capture", "--kind", "claude", "--pane", PANE, "--timeout", "5000")
UNKNOWN_SESSION = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True)
class Certificates:
    ca: Path
    client: Issued
    rogue: Issued


@pytest.fixture(scope="module")
def certificates(tmp_path_factory: pytest.TempPathFactory) -> Certificates:
    root = tmp_path_factory.mktemp("herdr-http")
    ca, client = ca_with_client(root, "app")
    return Certificates(ca, client, ca_with_client(root, "rogue")[1])


Replies = dict[tuple[str, ...], Outcome | Exception | list[Outcome]]


def replies(project: Path) -> Replies:
    return {
        ("agent", "list"): listing(), ("tab", "list"): ok("tab_list.json"),
        ("--version",): ok("version.out"), READ: ok("agent_read.txt"), PROMPT: ok("agent_prompt.json"),
        ("pane", "close", PANE): ok("pane_close.json"),
        ("tab", "create", "--cwd", str(project), "--label", "bridge-capture", "--no-focus"): ok("tab_create.json"),
        START: ok("agent_start.json")}


@dataclass
class World:
    served: Served
    project: Path
    certificates: Certificates

    def bridge(self, client: Issued | None = None) -> HttpBridge:
        cert = client or self.certificates.client
        return HttpBridge(ClientCertificate(str(cert.cert), str(cert.key)), replace(load(), timeout_s=5.0))

    def access(self, **changes: object) -> Access:
        return replace(Access(f"https://127.0.0.1:{self.served.port}", self.served.pin, TOKEN, int(PERSON)), **changes)

    def herdr_calls(self) -> list[tuple[str, ...]]:
        return self.served.bridge.runner.calls


@pytest.fixture
def world(tmp_path: Path, certificates: Certificates) -> Generator[World]:
    project = tmp_path / "project"
    project.mkdir()
    with serving(tmp_path, certificates.ca, FakeHerdr(replies(project)), roots=(str(tmp_path),)) as served:
        yield World(served, project, certificates)


def run(call: Awaitable[T]) -> T:
    return asyncio.run(asyncio.wait_for(call, 20))


def refused(call: Awaitable[object]) -> str:
    with pytest.raises(BridgeFailed) as caught:
        run(call)
    return caught.value.reason


def test_whoami_names_the_versions_and_records_the_person(world: World) -> None:
    got = run(world.bridge().whoami(world.access()))
    assert (got.herdr_version, got.person) == ("0.9.5", PERSON)


def test_sessions_are_the_captured_listing_as_values(world: World) -> None:
    got = run(world.bridge().sessions(world.access()))
    assert [s.label for s in got.sessions] == ["app-2", "bridge-capture", "notes", "1", "1"]
    assert [s.status for s in got.sessions] == ["working", "done", "idle", "idle", "idle"]
    assert got.sessions[1].seq == 1631 and got.sessions[1].dir == "bridge-capture-dir"
    assert got.last_typed_at is None and got.sessions[0].last_typed_at is None


def test_sessions_carry_the_roots_the_bridge_was_set_up_with(world: World, tmp_path: Path) -> None:
    got = run(world.bridge().sessions(world.access()))
    assert got.roots == (str(tmp_path.resolve()),)


def test_a_bridge_that_sends_no_roots_leaves_them_unknown(world: World) -> None:
    older = {k: v for k, v in world.served.bridge.get("/v1/sessions").body.items() if k != "roots"}
    got = sessions(json.dumps(older).encode())
    assert got.roots is None and len(got.sessions) == 5


def test_read_returns_the_screen_text(world: World) -> None:
    got = run(world.bridge().read(world.access(), THROWAWAY, 120))
    assert got.text == (Path(__file__).parent / "herdr_captured" / "agent_read.txt").read_text()
    assert READ in world.herdr_calls()


def test_prompt_and_close_reach_herdr_as_the_bridge_sends_them(world: World) -> None:
    bridge, access = world.bridge(), world.access()
    run(bridge.prompt(access, THROWAWAY, "reply with ok"))
    run(bridge.close(access, THROWAWAY))
    assert PROMPT in world.herdr_calls() and ("pane", "close", PANE) in world.herdr_calls()


def test_start_returns_the_session_once_it_reports_a_state(tmp_path: Path, certificates: Certificates) -> None:
    project = tmp_path / "project"
    project.mkdir()
    table = {**replies(project), ("agent", "list"): [listing(drop=(THROWAWAY,)), listing()]}
    with serving(tmp_path, certificates.ca, FakeHerdr(table), roots=(str(tmp_path),)) as served:
        world = World(served, project, certificates)
        started = run(world.bridge().start(world.access(), str(project), "bridge-capture", None))
    assert (started.id, started.status, started.label) == (THROWAWAY, "done", "bridge-capture")


def test_start_in_a_directory_outside_the_roots_is_refused(world: World) -> None:
    assert refused(world.bridge().start(world.access(), "/etc", "bridge-capture", None)) == "dir_not_allowed"


def test_a_session_that_is_not_there_is_not_found(world: World) -> None:
    assert refused(world.bridge().read(world.access(), UNKNOWN_SESSION, 5)) == "not_found"


@pytest.mark.parametrize("bad", ["../whoami", "x", THROWAWAY + "/close", ""])
def test_a_session_id_that_is_not_an_id_never_leaves_the_app(world: World, bad: str) -> None:
    assert refused(world.bridge().close(world.access(), bad)) == "not_found"
    assert world.served.bridge.log.lines == []


def test_a_busy_session_refuses_the_prompt_in_the_bridges_words(tmp_path: Path, certificates: Certificates) -> None:
    project = tmp_path / "project"
    project.mkdir()
    table = {**replies(project), ("agent", "list"): listing({THROWAWAY: "working"})}
    with serving(tmp_path, certificates.ca, FakeHerdr(table)) as served:
        world = World(served, project, certificates)
        assert refused(world.bridge().prompt(world.access(), THROWAWAY, "reply with ok")) == "busy"
    assert PROMPT not in served.bridge.runner.calls


def test_a_prompt_that_timed_out_in_herdr_is_unconfirmed(tmp_path: Path, certificates: Certificates) -> None:
    project = tmp_path / "project"
    project.mkdir()
    table = {**replies(project), ("agent", "list"): listing(), PROMPT: HerdrTimeout("agent")}
    with serving(tmp_path, certificates.ca, FakeHerdr(table)) as served:
        world = World(served, project, certificates)
        assert refused(world.bridge().prompt(world.access(), THROWAWAY, "reply with ok")) == "unconfirmed"


def test_a_wrong_fingerprint_is_refused_and_nothing_is_sent(world: World) -> None:
    flipped = ("0" if world.served.pin[0] != "0" else "1") + world.served.pin[1:]
    assert refused(world.bridge().whoami(world.access(fingerprint=flipped))) == "pin_mismatch"
    assert not any(line.startswith("call=whoami") for line in world.served.bridge.log.lines)
    assert world.served.bridge.person_on_disk() is None


def test_a_wrong_token_is_bad_token(world: World) -> None:
    assert refused(world.bridge().sessions(world.access(token="not-the-token"))) == "bad_token"


def test_another_person_is_refused_once_the_first_owns_the_bridge(world: World) -> None:
    bridge = world.bridge()
    run(bridge.whoami(world.access()))
    assert refused(bridge.sessions(world.access(person=int(PERSON) + 1))) == "wrong_person"


def test_a_client_certificate_from_another_ca_gets_no_answer(world: World) -> None:
    assert refused(world.bridge(world.certificates.rogue).whoami(world.access())) == "herdr_unavailable"


def test_a_bridge_whose_herdr_is_not_running_is_herdr_unavailable(tmp_path: Path, certificates: Certificates) -> None:
    table: Replies = {("agent", "list"): HerdrMissing("herdr"), ("tab", "list"): HerdrMissing("herdr")}
    with serving(tmp_path, certificates.ca, FakeHerdr(table)) as served:
        world = World(served, tmp_path, certificates)
        assert refused(world.bridge().sessions(world.access())) == "herdr_unavailable"


def test_nothing_listening_at_the_address_is_herdr_unavailable(tmp_path: Path, certificates: Certificates) -> None:
    with serving(tmp_path, certificates.ca, FakeHerdr({})) as served:
        gone = Access(f"https://127.0.0.1:{served.port}", served.pin, TOKEN, int(PERSON))
    assert refused(HttpBridge(ClientCertificate(str(certificates.client.cert), str(certificates.client.key)),
                              replace(load(), timeout_s=5.0)).whoami(gone)) == "herdr_unavailable"


class Stalling(FakeHerdr):
    """A herdr that holds one command until released, so the bridge sits on a request the app has already sent."""

    def __init__(self, table: Replies, stalled: tuple[str, ...]) -> None:
        super().__init__(table)
        self.stalled = stalled
        self.release = threading.Event()

    def run(self, args: Sequence[str], timeout_s: float) -> Outcome:
        if tuple(args) == self.stalled:
            self.release.wait(10)
        return super().run(args, timeout_s)


@pytest.mark.parametrize("stalled,call,expected", [(PROMPT, "prompt", "unconfirmed"), (READ, "read", "herdr_unavailable")])
def test_an_answer_that_never_comes_is_unconfirmed_for_a_change_and_unavailable_for_a_read(
        tmp_path: Path, certificates: Certificates, stalled: tuple[str, ...], call: str, expected: str) -> None:
    herdr = Stalling(replies(tmp_path), stalled)
    with serving(tmp_path, certificates.ca, herdr) as served:
        world = World(served, tmp_path, certificates)
        impatient = HttpBridge(ClientCertificate(str(certificates.client.cert), str(certificates.client.key)),
                               replace(load(), timeout_s=0.5))
        try:
            asked = impatient.prompt(world.access(), THROWAWAY, "reply with ok") if call == "prompt" \
                else impatient.read(world.access(), THROWAWAY, 120)
            assert refused(asked) == expected
        finally:
            herdr.release.set()


def test_the_null_bridge_fails_every_call() -> None:
    null = NullBridge()
    access = Access("https://x:1", "0" * 64, "t", 1)
    for call in (null.whoami(access), null.sessions(access), null.read(access, THROWAWAY, 1),
                 null.prompt(access, THROWAWAY, "x"), null.start(access, "/d", "l", None), null.close(access, THROWAWAY)):
        assert refused(call) == "herdr_unavailable"


def test_an_unregistered_bridge_is_the_null_object() -> None:
    services.unregister(Bridge)
    assert isinstance(services.get(Bridge), NullBridge)


@pytest.fixture
def registered(world: World) -> Generator[World]:
    services.register(Bridge, world.bridge())
    yield world
    services.unregister(Bridge)


def check(world: World, token: str = TOKEN, person: int = int(PERSON), pin: str | None = None) -> Refusal | None:
    base = f"https://127.0.0.1:{world.served.port}#sha256={pin or world.served.pin}"
    return run(HERDR.check(base, token, person))


def test_the_kind_connects_when_the_bridge_answers_whoami_for_the_person(registered: World) -> None:
    assert check(registered) is None


def test_the_kind_refuses_a_token_the_bridge_turns_away(registered: World) -> None:
    assert check(registered, token="nope") == "key_refused"


def test_the_kind_refuses_a_person_the_bridge_does_not_serve(registered: World) -> None:
    assert check(registered) is None
    assert check(registered, person=int(PERSON) + 1) == "key_refused"


def test_the_kind_calls_a_certificate_with_another_fingerprint_the_wrong_service(registered: World) -> None:
    assert check(registered, pin="a" * 64) == "wrong_service"


def test_the_kind_calls_a_bridge_that_is_down_unreachable(tmp_path: Path, certificates: Certificates) -> None:
    with serving(tmp_path, certificates.ca, FakeHerdr({})) as served:
        base = f"https://127.0.0.1:{served.port}#sha256={served.pin}"
    services.register(Bridge, HttpBridge(ClientCertificate(str(certificates.client.cert), str(certificates.client.key)),
                                         replace(load(), timeout_s=5.0)))
    try:
        assert run(HERDR.check(base, TOKEN, 1)) == "unreachable"
    finally:
        services.unregister(Bridge)
