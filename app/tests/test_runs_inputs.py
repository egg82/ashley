"""Binary inputs reach a run by reference and travel as a tar on its init container's standard input, which the app
pushes through the Kubernetes API (`KubeApi.attach_stdin`): the pod has no network at all, and the run container
mounts what the init container verified, read-only."""

import asyncio
import base64
import hashlib
import io
import json
import tarfile
from collections.abc import AsyncIterable, Generator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2
import pytest
from ashley import services
from ashley.files.intake import key_of
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.runs import inputs, unpack
from ashley.runs.config import Profile
from ashley.runs.kube_api import KubeApi, KubeError
from ashley.runs.kubernetes import UNPACKER, KubernetesSandbox
from ashley.runs.model import InputFile, Job, Output
from ashley.runs.pod_spec import LABEL, manifest
from httpx2.websockets import ASGIWebSocketTransport
from sandbox_support import CONFIG, PYTHON, Clock, FakeKube, Script
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

CAD_IMAGE = "registry.test/cad@sha256:" + "c" * 64
CAD = Profile(CAD_IMAGE, 60, 120, "1", "500m", "1Gi", 32, 4096, 1024, 16 * 1024 * 1024)
RUNS = replace(CONFIG, languages={"python": PYTHON, "build123d": CAD})
DATA = {"7.stl": b"solid seven", "8.3mf": bytes(range(256)) * 700}
HOME = 3


def stored(data: bytes) -> InputFile:
    return InputFile(HOME, hashlib.sha256(data).hexdigest(), len(data))


JOB = Job("run-9", "build123d", "show(1)", inputs={name: stored(data) for name, data in DATA.items()})
WANT = {name: (f.size, f.sha256) for name, f in JOB.inputs.items()}


@pytest.fixture
def store() -> Generator[MemoryStore]:
    held = MemoryStore()
    services.register(ObjectStore, held)
    for data in DATA.values():
        asyncio.run(held.put(key_of(HOME, hashlib.sha256(data).hexdigest()), data))
    yield held
    services.unregister(ObjectStore)


async def collected(chunks: AsyncIterable[bytes]) -> bytes:
    return b"".join([c async for c in chunks])


def tar_of(files: dict[str, bytes], **kinds: Any) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            for key, value in kinds.items():
                setattr(info, key, value)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


# --- the pod ---

def test_a_job_with_inputs_gets_an_init_container_with_stdin_and_a_volume_the_run_mounts_read_only() -> None:
    pod = manifest(JOB, RUNS, "RUNNER", "gvisor", "UNPACKER")
    spec = pod["spec"]
    (init,), (run,) = spec["initContainers"], spec["containers"]
    assert init["command"][-1] == "UNPACKER" and init["stdin"] is True and init["stdinOnce"] is True
    assert init["volumeMounts"] == [{"name": "inputs", "mountPath": "/inputs"}]
    assert {"name": "inputs", "mountPath": "/work/inputs", "readOnly": True} in run["volumeMounts"]
    assert {"name": "inputs", "emptyDir": {"sizeLimit": "16Mi"}} in spec["volumes"]
    assert init["securityContext"]["readOnlyRootFilesystem"] and init["securityContext"]["capabilities"] == {"drop": ["ALL"]}


def test_the_pod_with_inputs_has_no_network_route_label_url_or_bytes() -> None:
    pod = manifest(JOB, RUNS, "RUNNER", "gvisor", "UNPACKER")
    assert pod["metadata"]["labels"] == {LABEL: "true"}
    assert pod["spec"]["dnsConfig"] == {"nameservers": ["127.0.0.1"]} and pod["spec"]["hostNetwork"] is False
    text = json.dumps(pod)
    assert "http" not in text.replace("https://", "") and "/api/files/" not in text and "ASHLEY_BLOB" not in text
    names = {e["name"] for c in (*pod["spec"]["initContainers"], *pod["spec"]["containers"]) for e in c["env"]}
    assert names == {"ASHLEY_INPUTS", "ASHLEY_SCRIPT", "ASHLEY_STDIN", "ASHLEY_LIMITS"}


def test_a_job_without_inputs_makes_no_init_container_or_volume() -> None:
    pod = manifest(Job("run-1", "python", "x"), RUNS, "RUNNER", "gvisor")
    assert "initContainers" not in pod["spec"] and [v["name"] for v in pod["spec"]["volumes"]] == ["work", "out"]


# --- the init container's program ---

def test_the_unpacker_keeps_exactly_the_named_files_when_size_and_digest_match(tmp_path: Path) -> None:
    unpack.unpack(io.BytesIO(tar_of(DATA)), WANT, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == DATA
    assert all(not (p.stat().st_mode & 0o222) for p in tmp_path.iterdir())


def altered(name: str, data: bytes) -> dict[str, bytes]:
    return {**DATA, name: data}


@pytest.mark.parametrize("files,why", [
    (altered("7.stl", b"solid sevex"), "digest"),
    (altered("7.stl", b"solid seven and more"), "size"),
    ({"7.stl": DATA["7.stl"]}, "missing"),
    ({**DATA, "9.stl": b"x"}, "extra"),
    ({"../7.stl": DATA["7.stl"], "8.3mf": DATA["8.3mf"]}, "climbing name"),
])
def test_the_unpacker_fails_for_a_stream_that_is_not_what_was_named(tmp_path: Path, files: dict[str, bytes], why: str) -> None:
    with pytest.raises(ValueError):
        unpack.unpack(io.BytesIO(tar_of(files)), WANT, tmp_path)


def test_the_unpacker_refuses_a_link_in_place_of_a_file(tmp_path: Path) -> None:
    link = tar_of({"7.stl": b""}, type=tarfile.SYMTYPE, linkname="/etc/passwd")
    with pytest.raises(ValueError):
        unpack.unpack(io.BytesIO(link), {"7.stl": (0, hashlib.sha256(b"").hexdigest())}, tmp_path)


def test_the_unpacker_exits_1_with_a_message_naming_no_name_when_it_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                         capsys: pytest.CaptureFixture[str]) -> None:
    task = {"files": [{"name": "7.stl", "size": 3, "sha256": "0" * 64}]}
    monkeypatch.setattr(unpack, "INPUTS", tmp_path)
    monkeypatch.setattr(unpack.os, "environ", {"ASHLEY_INPUTS": base64.b64encode(json.dumps(task).encode()).decode()})
    monkeypatch.setattr(unpack.sys, "stdin", io.TextIOWrapper(io.BytesIO(tar_of({"7.stl": b"abc"}))))
    with pytest.raises(SystemExit) as stopped:
        unpack.main()
    assert stopped.value.code == 1 and "7.stl" not in capsys.readouterr().err


# --- the app's end: the tar ---

def test_the_tar_streams_each_file_in_name_order_and_the_unpacker_accepts_it(store: MemoryStore, tmp_path: Path) -> None:
    data = asyncio.run(collected(inputs.tar(JOB.inputs)))
    unpack.unpack(io.BytesIO(data), WANT, tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == DATA


def test_the_tar_reads_one_file_at_a_time_and_in_small_chunks(store: MemoryStore,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        reads: list[str] = []
        real = store.get

        async def counting(key: str) -> bytes | None:
            reads.append(key)
            return await real(key)

        monkeypatch.setattr(store, "get", counting)
        chunks = inputs.tar(JOB.inputs)
        await anext(chunks)
        assert len(reads) == 1
        sizes = [len(c) async for c in chunks]
        assert len(reads) == 2 and max(sizes) <= inputs.CHUNK and len(DATA["8.3mf"]) > 2 * inputs.CHUNK

    asyncio.run(scenario())


@pytest.mark.parametrize("damage", ["gone", "other bytes", "store down"])
def test_the_tar_raises_for_an_input_the_store_does_not_give_intact(store: MemoryStore, damage: str) -> None:
    key = key_of(HOME, JOB.inputs["7.stl"].sha256)
    if damage == "gone":
        asyncio.run(store.delete(key))
    elif damage == "other bytes":
        asyncio.run(store.put(key, b"solid sevex"))
    else:
        store.down = True
    with pytest.raises(inputs.InputUnavailable):
        asyncio.run(collected(inputs.tar(JOB.inputs)))


# --- the app's end: the attach ---

class Attached(KubeApi):
    """A KubeApi whose attach is recorded instead of made: the bytes the init container would have read."""

    sent: bytes = b""
    refuse: bool = False

    async def attach_stdin(self, namespace: str, name: str, container: str, chunks: AsyncIterable[bytes],
                           timeout_s: float) -> None:
        self.target = (namespace, name, container)
        self.sent = await collected(chunks)
        if self.refuse:
            raise KubeError("http 403")


def run_with(tmp_path: Path, script: Script | None = None, refuse: bool = False, job: Job = JOB) -> tuple[FakeKube, Attached, Output]:
    fake, clock = FakeKube(tmp_path / "token", script or Script()), Clock()
    (tmp_path / "token").write_text("t")
    api = Attached(httpx2.AsyncClient(base_url="https://kube.test", transport=httpx2.MockTransport(fake.handle)),
                   str(tmp_path / "token"))
    api.refuse = refuse
    done = asyncio.run(KubernetesSandbox(api, RUNS, "ashley-sandbox", "gvisor", sleep=clock.sleep, clock=clock).run(job))
    return fake, api, done


def test_the_sandbox_pushes_the_inputs_into_the_running_init_container_and_the_run_goes_on(store: MemoryStore, tmp_path: Path,
                                                                                              ) -> None:
    fake, api, done = run_with(tmp_path)
    assert api.target == ("ashley-sandbox", "run-9", "unpack") and done.outcome == "ran"
    unpack.unpack(io.BytesIO(api.sent), WANT, tmp_path)
    assert fake.created[0]["spec"]["initContainers"][0]["command"][-1] == UNPACKER


def test_the_sandbox_waits_for_the_init_container_to_run_before_it_attaches(store: MemoryStore, tmp_path: Path) -> None:
    fake, api, done = run_with(tmp_path, Script(phases=["Pending"], init_state={"waiting": {}}))
    assert api.sent == b"" and (done.outcome, done.exit_code) == ("failed", None)
    assert "did not run" in done.stderr and fake.deleted == ["run-9"]


def test_an_attach_the_api_refuses_is_a_failed_run_and_the_pod_is_deleted(store: MemoryStore, tmp_path: Path) -> None:
    fake, _, done = run_with(tmp_path, refuse=True)
    assert (done.outcome, done.exit_code) == ("failed", None) and "did not run" in done.stderr and fake.deleted == ["run-9"]


def test_an_input_that_is_not_what_it_was_when_named_fails_the_run_before_any_byte_is_sent_on(store: MemoryStore, tmp_path: Path) -> None:
    asyncio.run(store.put(key_of(HOME, JOB.inputs["7.stl"].sha256), b"solid sevex"))
    fake, _, done = run_with(tmp_path)
    assert done.outcome == "failed" and "did not run" in done.stderr and fake.deleted == ["run-9"]


def test_an_init_container_that_rejected_the_stream_is_reported_failed_not_unknown(store: MemoryStore, tmp_path: Path) -> None:
    _, _, done = run_with(tmp_path, Script(phases=["Pending", "Failed"], log="", log_status=400, init_exit=1))
    assert (done.outcome, done.exit_code) == ("failed", None) and "input" in done.stderr


# --- the attach over a WebSocket ---

def test_attach_stdin_sends_stdin_frames_then_the_close_signal_and_reads_the_status(tmp_path: Path) -> None:
    seen: list[Any] = []

    async def socket(ws: WebSocket) -> None:
        await ws.accept(subprotocol="v5.channel.k8s.io")
        seen.append((ws.url.path, dict(ws.query_params), ws.headers["authorization"], ws.scope["subprotocols"]))
        while (frame := await ws.receive())["type"] != "websocket.disconnect":
            seen.append(frame["bytes"])
            if frame["bytes"] == bytes([255, 0]):
                await ws.send_bytes(b'\x03{"status":"Success"}')
                await ws.close()
                return

    async def chunks() -> AsyncIterable[bytes]:
        yield b"ab"
        yield b"cd"

    async def scenario() -> None:
        (tmp_path / "t").write_text("tok\n")
        app = Starlette(routes=[WebSocketRoute("/api/v1/namespaces/ns/pods/p/attach", socket)])
        async with httpx2.AsyncClient(base_url="http://kube.test", transport=ASGIWebSocketTransport(app)) as http:
            await KubeApi(http, str(tmp_path / "t")).attach_stdin("ns", "p", "unpack", chunks(), 5)

    asyncio.run(scenario())
    path, query, auth, protocols = seen[0]
    assert (path, auth) == ("/api/v1/namespaces/ns/pods/p/attach", "Bearer tok")
    assert query == {"container": "unpack", "stdin": "true", "stdout": "false", "stderr": "false", "tty": "false"}
    assert protocols[0] == "v5.channel.k8s.io" and seen[1:] == [b"\x00ab", b"\x00cd", bytes([255, 0])]


@pytest.mark.xfail(strict=True, reason="an empty status frame before the status is read as a failure")
def test_attach_stdin_accepts_the_empty_status_frame_the_api_server_sends_before_success(tmp_path: Path) -> None:
    async def socket(ws: WebSocket) -> None:
        await ws.accept(subprotocol="v5.channel.k8s.io")
        while (frame := await ws.receive())["type"] != "websocket.disconnect":
            if frame["bytes"] == bytes([255, 0]):
                await ws.send_bytes(b"\x03")
                await ws.send_bytes(b'\x03{"metadata":{},"status":"Success"}')
                await ws.close()
                return

    async def chunks() -> AsyncIterable[bytes]:
        yield b"ab"

    async def scenario() -> None:
        (tmp_path / "t").write_text("tok")
        app = Starlette(routes=[WebSocketRoute("/api/v1/namespaces/ns/pods/p/attach", socket)])
        async with httpx2.AsyncClient(base_url="http://kube.test", transport=ASGIWebSocketTransport(app)) as http:
            await KubeApi(http, str(tmp_path / "t")).attach_stdin("ns", "p", "unpack", chunks(), 5)

    asyncio.run(scenario())


def test_attach_stdin_raises_when_the_container_reports_a_failure_or_the_source_fails(tmp_path: Path) -> None:
    async def socket(ws: WebSocket) -> None:
        await ws.accept(subprotocol="v5.channel.k8s.io")
        while (frame := await ws.receive())["type"] != "websocket.disconnect":
            if frame["bytes"] == bytes([255, 0]):
                await ws.send_bytes(b'\x03{"status":"Failure"}')
                await ws.close()
                return

    async def good() -> AsyncIterable[bytes]:
        yield b"ab"

    async def bad() -> AsyncIterable[bytes]:
        yield b"ab"
        raise inputs.InputUnavailable("gone")

    async def scenario() -> None:
        (tmp_path / "t").write_text("tok")
        app = Starlette(routes=[WebSocketRoute("/api/v1/namespaces/ns/pods/p/attach", socket)])
        async with httpx2.AsyncClient(base_url="http://kube.test", transport=ASGIWebSocketTransport(app)) as http:
            api = KubeApi(http, str(tmp_path / "t"))
            with pytest.raises(KubeError):
                await api.attach_stdin("ns", "p", "unpack", good(), 5)
            with pytest.raises(inputs.InputUnavailable):
                await api.attach_stdin("ns", "p", "unpack", bad(), 5)

    asyncio.run(scenario())
