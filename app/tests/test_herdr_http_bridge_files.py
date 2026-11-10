"""`HttpBridge`'s file calls against the real bridge program over real mutual TLS."""

import asyncio
import json
import os
from collections.abc import Awaitable, Generator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TypeVar

import pytest
from ashley.herdr.bridge import NullBridge
from ashley.herdr.config import load
from ashley.herdr.http_bridge import HttpBridge
from ashley.herdr.model import Access, BridgeFailed, OutFile
from ashley.herdr.transport import ClientCertificate
from ashley.herdr.wire import whoami
from herdr_bridge.files import Limits

from herdr_bridge_support import PERSON, THROWAWAY, TOKEN, FakeHerdr, Served, ca_with_client, listing, ok, serving

T = TypeVar("T")
LIMITS = Limits(max_file_bytes=64, max_files=2)


@dataclass
class World:
    served: Served
    bridge: HttpBridge
    project: Path
    outside: Path

    def access(self) -> Access:
        return Access(f"https://127.0.0.1:{self.served.port}", self.served.pin, TOKEN, int(PERSON))


@pytest.fixture
def world(tmp_path: Path) -> Generator[World]:
    ca, client = ca_with_client(tmp_path, "app")
    root, outside = tmp_path / "root", tmp_path / "outside"
    project = root / "project"
    project.mkdir(parents=True)
    outside.mkdir()
    runner = FakeHerdr({("agent", "list"): listing(cwds={THROWAWAY: str(project)}), ("tab", "list"): ok("tab_list.json"),
                        ("--version",): ok("version.out")})
    bridge = HttpBridge(ClientCertificate(str(client.cert), str(client.key)), replace(load(), timeout_s=5.0))
    with serving(tmp_path, ca, runner, (str(root),), LIMITS) as served:
        yield World(served, bridge, project, outside)


def run(call: Awaitable[T]) -> T:
    return asyncio.run(asyncio.wait_for(call, 20))


def refused(call: Awaitable[object]) -> str:
    with pytest.raises(BridgeFailed) as caught:
        run(call)
    return caught.value.reason


def test_whoami_lists_the_files_capability(world: World) -> None:
    assert run(world.bridge.whoami(world.access())).capabilities == ("files",)


def test_a_bridge_that_sends_no_capabilities_reads_as_having_none() -> None:
    older = json.dumps({"bridge_version": "0.1.0", "herdr_version": None, "person": "7"}).encode()
    assert whoami(older).capabilities == ()


def test_an_upload_lands_as_the_exact_bytes(world: World) -> None:
    data = b"\x00\xff\r\nbinary"
    assert run(world.bridge.upload(world.access(), THROWAWAY, "p1-run.step", data)) is None
    assert (world.project / "in" / "p1-run.step").read_bytes() == data


def test_outputs_and_downloads_round_trip(world: World) -> None:
    out = world.project / "out"
    out.mkdir()
    (out / "RESULT.md").write_bytes(b"# done\n")
    (out / "model.step").write_bytes(b"\x00\x01\x02")
    access = world.access()
    assert run(world.bridge.outputs(access, THROWAWAY)) == (OutFile("RESULT.md", 7), OutFile("model.step", 3))
    assert run(world.bridge.download(access, THROWAWAY, "model.step", 64)) == b"\x00\x01\x02"


def test_no_out_directory_lists_nothing(world: World) -> None:
    assert run(world.bridge.outputs(world.access(), THROWAWAY)) == ()


def test_a_download_over_max_bytes_is_too_large_even_when_max_is_tiny(world: World) -> None:
    (world.project / "out").mkdir()
    (world.project / "out" / "f").write_bytes(b"12345")
    assert refused(world.bridge.download(world.access(), THROWAWAY, "f", 4)) == "too_large"
    assert run(world.bridge.download(world.access(), THROWAWAY, "f", 5)) == b"12345"
    assert refused(world.bridge.download(world.access(), THROWAWAY, "missing", 1)) == "not_found"


def test_a_file_over_the_bridges_limit_is_too_large_for_both_directions(world: World) -> None:
    access = world.access()
    assert refused(world.bridge.upload(access, THROWAWAY, "big", b"x" * 65)) == "too_large"
    assert not (world.project / "in").exists()
    (world.project / "out").mkdir()
    (world.project / "out" / "big").write_bytes(b"x" * 65)
    assert refused(world.bridge.download(access, THROWAWAY, "big", 10**6)) == "too_large"


def test_uploads_past_the_bridges_file_count_are_too_many(world: World) -> None:
    for name in ("a", "b"):
        run(world.bridge.upload(world.access(), THROWAWAY, name, b"x"))
    assert refused(world.bridge.upload(world.access(), THROWAWAY, "c", b"x")) == "too_many"


def test_a_symlinked_in_or_out_is_bad_path(world: World) -> None:
    (world.project / "in").symlink_to(world.outside)
    (world.project / "out").symlink_to(world.outside)
    access = world.access()
    assert refused(world.bridge.upload(access, THROWAWAY, "a", b"x")) == "bad_path"
    assert refused(world.bridge.outputs(access, THROWAWAY)) == "bad_path"
    assert os.listdir(world.outside) == []


@pytest.mark.parametrize("bad", ["../x", "a/b", ".env", "", "a b", "a\x00b", "x" * 101])
def test_a_name_the_bridge_would_refuse_never_leaves_the_app(world: World, bad: str) -> None:
    assert refused(world.bridge.upload(world.access(), THROWAWAY, bad, b"x")) == "bad_request"
    assert refused(world.bridge.download(world.access(), THROWAWAY, bad, 10)) == "bad_request"
    assert world.served.bridge.log.lines == []


def test_a_session_id_that_is_not_an_id_never_leaves_the_app(world: World) -> None:
    assert refused(world.bridge.upload(world.access(), "../x", "a", b"x")) == "not_found"
    assert refused(world.bridge.outputs(world.access(), "x")) == "not_found"
    assert world.served.bridge.log.lines == []


def test_an_unknown_session_is_not_found(world: World) -> None:
    assert refused(world.bridge.outputs(world.access(), "00000000-0000-0000-0000-000000000000")) == "not_found"


def test_the_null_bridge_cannot_move_files() -> None:
    null = NullBridge()
    access = Access("https://x", "0" * 64, "t", 1)
    for call in (null.upload(access, THROWAWAY, "a", b""), null.outputs(access, THROWAWAY),
                 null.download(access, THROWAWAY, "a", 1)):
        assert refused(call) == "herdr_unavailable"
