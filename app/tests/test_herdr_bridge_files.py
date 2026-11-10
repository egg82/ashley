"""The bridge's file transfer: `in/` and `out/` of a session's directory, and nothing else of it."""

import http.client
import json
import os
import ssl
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from herdr_bridge.api import Request, Response
from herdr_bridge.config import Config, load
from herdr_bridge.files import Limits

from herdr_bridge_support import (PERSON, THROWAWAY, TOKEN, Bridge, FakeHerdr, Issued, ca_with_client, digest8, listing,
                                  ok, serving)

LIST = ("agent", "list")
TABS = ("tab", "list")
SMALL = Limits(max_file_bytes=64, max_files=2)


@dataclass
class Setup:
    bridge: Bridge
    root: Path
    project: Path  # the session's directory
    outside: Path  # a directory the bridge was not given

    def path(self, tail: str, session: str = THROWAWAY) -> str:
        return f"/v1/sessions/{session}{tail}"

    def put(self, name: str, data: bytes, declared: int | None = None, session: str = THROWAWAY,
            **headers: str) -> Response:
        head = {**self.bridge.headers(headers), "content-length": str(len(data) if declared is None else declared)}
        return self.bridge.api.handle(Request("PUT", self.path(f"/in/{name}", session), {}, head, data))

    def get(self, tail: str, session: str = THROWAWAY) -> Response:
        return self.bridge.get(self.path(tail, session))


def setup(tmp_path: Path, limits: Limits = SMALL, cwd: str | None = None) -> Setup:
    root, outside = tmp_path / "root", tmp_path / "outside"
    project = root / "project"
    for d in (project, outside, tmp_path / "state"):
        d.mkdir(parents=True)
    runner = FakeHerdr({LIST: listing(cwds={THROWAWAY: cwd or str(project)}), TABS: ok("tab_list.json")})
    return Setup(Bridge(tmp_path / "state", runner, (str(root),), limits), root, project, outside)


def test_an_upload_lands_in_in_and_answers_its_size(tmp_path: Path) -> None:
    s = setup(tmp_path)
    res = s.put("p1.py", b"print(1)\n")
    assert (res.status, res.body) == (200, {"bytes": 9})
    assert (s.project / "in" / "p1.py").read_bytes() == b"print(1)\n"
    assert sorted(os.listdir(s.project / "in")) == ["p1.py"], "no temporary file is left behind"


def test_an_upload_replaces_a_file_of_the_same_name(tmp_path: Path) -> None:
    s = setup(tmp_path)
    s.put("a.txt", b"one")
    assert s.put("a.txt", b"two!").status == 200
    assert (s.project / "in" / "a.txt").read_bytes() == b"two!"


BAD_NAMES = ["..", ".", ".env", ".hidden", "a b", "%2e%2e", "a\x00b", "a\nb", "x" * 101, "a/b", "a/../b", "/", "..%2f", "-x"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_a_name_that_is_not_flat_is_refused_and_nothing_is_written(tmp_path: Path, name: str) -> None:
    s = setup(tmp_path)
    res = s.put(name, b"x")
    assert (res.status, res.body) == (400, {"error": "bad_request"})
    assert not (s.project / "in").exists()
    assert [p for p in s.root.rglob("*") if p.is_file()] == []
    assert s.bridge.runner.calls == [], "a bad name never reaches herdr"


@pytest.mark.parametrize("name", [*BAD_NAMES, ""])
def test_a_download_name_that_is_not_flat_is_refused(tmp_path: Path, name: str) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    (s.project / ".env").write_text("SECRET")
    (s.outside / "loot").write_text("SECRET")
    res = s.get(f"/out/{name}")
    assert (res.status, res.body, res.raw) == (400, {"error": "bad_request"}, None)


def test_a_name_of_a_hundred_characters_is_the_longest_accepted(tmp_path: Path) -> None:
    s = setup(tmp_path)
    assert s.put("a" * 100, b"x").status == 200


def test_a_symlinked_in_is_refused_and_nothing_lands_where_it_points(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "in").symlink_to(s.outside)
    res = s.put("p1.py", b"x")
    assert (res.status, res.body) == (400, {"error": "bad_path"})
    assert os.listdir(s.outside) == []


def test_a_symlinked_out_is_refused_for_listing_and_download(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.outside / "loot").write_text("SECRET")
    (s.project / "out").symlink_to(s.outside)
    for tail in ("/out", "/out/loot"):
        res = s.get(tail)
        assert (res.status, res.body, res.raw) == (400, {"error": "bad_path"}, None)


def test_in_that_is_a_file_is_bad_path(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "in").write_text("not a directory")
    assert s.put("a", b"x").body == {"error": "bad_path"}


def test_an_upload_over_a_name_that_is_a_directory_is_refused_and_leaves_no_temporary(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "in" / "taken").mkdir(parents=True)
    assert s.put("taken", b"x").body == {"error": "bad_path"}
    assert os.listdir(s.project / "in") == ["taken"]


def test_an_upload_does_not_follow_a_symlink_of_the_same_name(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "in").mkdir()
    (s.outside / "target").write_text("keep")
    (s.project / "in" / "link").symlink_to(s.outside / "target")
    assert s.put("link", b"new").status == 200
    assert (s.outside / "target").read_text() == "keep"
    assert not (s.project / "in" / "link").is_symlink()


def test_a_body_over_the_limit_is_413_by_its_declared_length_before_any_is_read(tmp_path: Path) -> None:
    s = setup(tmp_path)
    res = s.put("big", b"", declared=65)
    assert (res.status, res.body) == (413, {"error": "too_large"})
    assert not (s.project / "in").exists()


def test_a_body_that_arrives_over_the_limit_is_413_whatever_it_declared(tmp_path: Path) -> None:
    s = setup(tmp_path)
    assert s.put("big", b"x" * 65, declared=10).body == {"error": "too_large"}
    assert s.put("big", b"x" * 65).body == {"error": "too_large"}
    assert not (s.project / "in").exists()


def test_a_body_at_the_limit_is_accepted(tmp_path: Path) -> None:
    s = setup(tmp_path)
    assert s.put("exact", b"x" * 64).status == 200


def test_a_short_chunked_or_undeclared_body_is_a_bad_request(tmp_path: Path) -> None:
    s = setup(tmp_path)
    assert s.put("a", b"abc", declared=10).body == {"error": "bad_request"}
    head = {k: v for k, v in s.bridge.headers({}).items()}
    for extra in ({}, {"transfer-encoding": "chunked", "content-length": "3"}, {"content-length": "-3"}):
        res = s.bridge.api.handle(Request("PUT", s.path("/in/a"), {}, {**head, **extra}, b"abc"))
        assert res.body == {"error": "bad_request"}
    assert not (s.project / "in").exists()


def test_uploads_past_max_files_are_too_many_but_a_replacement_is_not(tmp_path: Path) -> None:
    s = setup(tmp_path)
    assert [s.put(n, b"x").status for n in ("a", "b")] == [200, 200]
    res = s.put("c", b"x")
    assert (res.status, res.body) == (409, {"error": "too_many"})
    assert s.put("a", b"y").status == 200
    assert sorted(os.listdir(s.project / "in")) == ["a", "b"]


def test_a_session_whose_directory_is_outside_the_roots_is_dir_not_allowed_for_every_call(tmp_path: Path) -> None:
    s = setup(tmp_path)
    out = s.outside
    runner = FakeHerdr({LIST: listing(cwds={THROWAWAY: str(out)}), TABS: ok("tab_list.json")})
    s.bridge.runner.replies = runner.replies
    (out / "out").mkdir()
    (out / "out" / "f").write_text("SECRET")
    assert s.put("a", b"x").body == {"error": "dir_not_allowed"}
    assert s.get("/out").body == {"error": "dir_not_allowed"}
    res = s.get("/out/f")
    assert (res.status, res.body, res.raw) == (403, {"error": "dir_not_allowed"}, None)
    assert not (out / "in").exists()


def test_a_session_dir_reached_through_a_symlink_out_of_the_roots_is_dir_not_allowed(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.root / "jump").symlink_to(s.outside)
    s.bridge.runner.replies = FakeHerdr({LIST: listing(cwds={THROWAWAY: str(s.root / "jump")}),
                                         TABS: ok("tab_list.json")}).replies
    assert s.put("a", b"x").body == {"error": "dir_not_allowed"}
    assert os.listdir(s.outside) == []


def test_a_session_dir_that_is_gone_is_dir_not_allowed(tmp_path: Path) -> None:
    s = setup(tmp_path, cwd=str(tmp_path / "root" / "missing"))
    assert s.get("/out").body == {"error": "dir_not_allowed"}


def test_an_unlisted_session_is_not_found(tmp_path: Path) -> None:
    s = setup(tmp_path)
    other = "00000000-0000-0000-0000-000000000000"
    assert s.put("a", b"x", session=other).status == 404
    assert s.get("/out", session=other).status == 404
    assert s.get("/out/a", session=other).status == 404


def test_the_listing_holds_only_regular_files_directly_in_out(tmp_path: Path) -> None:
    s = setup(tmp_path)
    out = s.project / "out"
    out.mkdir()
    (out / "b.txt").write_bytes(b"12345")
    (out / "a.txt").write_bytes(b"")
    (out / "sub").mkdir()
    (out / "sub" / "deep.txt").write_text("x")
    (out / "link").symlink_to(s.outside)
    (s.project / "real.txt").write_text("x")
    (out / "flink").symlink_to(s.project / "real.txt")
    os.mkfifo(out / "pipe")
    (out / ".hidden").write_text("x")
    (out / "bad name").write_text("x")
    res = s.get("/out")
    assert (res.status, res.body) == (200, {"files": [{"name": "a.txt", "bytes": 0}, {"name": "b.txt", "bytes": 5}]})


def test_a_missing_out_lists_nothing(tmp_path: Path) -> None:
    assert setup(tmp_path).get("/out").body == {"files": []}


def test_a_listing_past_max_files_is_too_many(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    for n in "abc":
        (s.project / "out" / n).write_text("x")
    assert s.get("/out").body == {"error": "too_many"}


def test_a_download_answers_the_raw_bytes(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    data = bytes(range(256))[:60]
    (s.project / "out" / "r.bin").write_bytes(data)
    res = s.get("/out/r.bin")
    assert (res.status, res.raw) == (200, data)


def test_a_download_reads_nothing_outside_out(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    (s.project / "secret.txt").write_text("SECRET")
    (s.project / "out" / "sub").mkdir()
    (s.project / "out" / "sub" / "deep").write_text("SECRET")
    (s.outside / "loot").write_text("SECRET")
    (s.project / "out" / "via").symlink_to(s.outside / "loot")
    (s.project / "out" / "up").symlink_to(s.project / "secret.txt")
    for name, code in (("secret.txt", "not_found"), ("sub", "bad_path"), ("via", "bad_path"), ("up", "bad_path"),
                       ("missing", "not_found")):
        res = s.get(f"/out/{name}")
        assert res.raw is None and res.body == {"error": code}, name
    assert s.get("/out/sub/deep").body == {"error": "bad_request"}


def test_a_download_of_a_fifo_is_refused_without_blocking(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    os.mkfifo(s.project / "out" / "pipe")
    assert s.get("/out/pipe").body == {"error": "bad_path"}


def test_a_download_over_the_limit_is_413(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    (s.project / "out" / "big").write_bytes(b"x" * 65)
    (s.project / "out" / "edge").write_bytes(b"x" * 64)
    assert s.get("/out/big").body == {"error": "too_large"}
    assert s.get("/out/edge").status == 200


def test_a_missing_out_is_not_found_for_a_download(tmp_path: Path) -> None:
    assert setup(tmp_path).get("/out/a").status == 404


def test_the_transfer_routes_answer_only_their_own_methods(tmp_path: Path) -> None:
    s = setup(tmp_path)
    for method, tail in (("GET", "/in/a"), ("POST", "/in/a"), ("PUT", "/in"), ("PUT", "/out/a"), ("POST", "/out"),
                         ("DELETE", "/out/a")):
        res = s.bridge.api.handle(Request(method, s.path(tail), {}, {**s.bridge.headers({}), "content-length": "0"}, b""))
        assert (res.status, res.body) == (404, {"error": "not_found"}), (method, tail)


def test_the_transfer_routes_need_the_token_and_the_person(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    assert s.put("a", b"x", authorization="Bearer nope").status == 401
    assert s.bridge.get(s.path("/out"), authorization="Bearer nope").status == 401
    assert s.get("/out").status == 200
    assert s.put("a", b"x", x_ashley_person="8").status == 403
    assert s.bridge.get(s.path("/out/a"), x_ashley_person="8").status == 403
    assert s.bridge.runner.calls.count(LIST) == 1


def test_the_log_carries_the_call_session_status_and_bytes_and_never_a_name(tmp_path: Path) -> None:
    s = setup(tmp_path)
    (s.project / "out").mkdir()
    (s.project / "out" / "secretname.txt").write_bytes(b"12345")
    s.put("uploadedname.py", b"123")
    s.get("/out")
    s.get("/out/secretname.txt")
    s.get("/out/missing")
    s.put("uploadedname.py", b"x" * 99)
    lines = s.bridge.log.lines
    sid = digest8(THROWAWAY)
    prefixes = [line.rsplit(" ms=", 1)[0] for line in lines]
    assert prefixes == [f"call=upload session={sid} status=200", f"call=outputs session={sid} status=200",
                        f"call=download session={sid} status=200", f"call=download session={sid} status=404",
                        f"call=upload session={sid} status=413"]
    assert [line.split(" bytes=")[1].split(" ")[0] for line in lines][0::2][:2] == ["3", "5"]
    assert not any(w in line for line in lines for w in ("secretname", "uploadedname", THROWAWAY, str(tmp_path)))


def test_the_limits_come_from_the_config_with_defaults(tmp_path: Path) -> None:
    base = Config("h", 1, ("/r",), "/s", "/ca")
    assert (base.max_file_bytes, base.max_files) == (26214400, 32)
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    path = tmp_path / "c.json"
    Config("h", 1, ("/r",), "/s", str(ca), max_file_bytes=7, max_files=3).dump(path)
    assert (load(path).max_file_bytes, load(path).max_files) == (7, 3)
    raw = json.loads(path.read_text())
    del raw["max_file_bytes"], raw["max_files"]
    path.write_text(json.dumps(raw))
    assert (load(path).max_file_bytes, load(path).max_files) == (26214400, 32)


@dataclass
class Wire:
    port: int
    client: Issued
    project: Path

    def call(self, method: str, path: str, body: bytes | None = None, declared: int | None = None) -> tuple[int, str, bytes]:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.load_cert_chain(self.client.cert, self.client.key)
        conn = http.client.HTTPSConnection("127.0.0.1", self.port, context=ctx, timeout=5)
        headers = {"Authorization": f"Bearer {TOKEN}", "X-Ashley-Person": PERSON}
        if declared is not None:
            headers["Content-Length"] = str(declared)
        try:
            conn.putrequest(method, path, skip_accept_encoding=True)
            for k, v in headers.items():
                conn.putheader(k, v)
            if body is None:
                conn.endheaders()
            else:
                conn.endheaders(body)
            res = conn.getresponse()
            return res.status, res.getheader("Content-Type", ""), res.read()
        finally:
            conn.close()


@pytest.fixture(scope="module")
def wire(tmp_path_factory: pytest.TempPathFactory) -> Generator[Wire]:
    root = tmp_path_factory.mktemp("files-tls")
    ca, client = ca_with_client(root, "files")
    project = root / "work" / "project"
    project.mkdir(parents=True)
    runner = FakeHerdr({LIST: listing(cwds={THROWAWAY: str(project)}), TABS: ok("tab_list.json"),
                        ("--version",): ok("version.out")})
    with serving(root, ca, runner, (str(root / "work"),), SMALL) as served:
        yield Wire(served.port, client, project)


def test_over_tls_a_file_goes_in_and_a_result_comes_out(wire: Wire) -> None:
    status, _, body = wire.call("PUT", f"/v1/sessions/{THROWAWAY}/in/p1.py", b"hello", 5)
    assert (status, json.loads(body)) == (200, {"bytes": 5})
    assert (wire.project / "in" / "p1.py").read_bytes() == b"hello"
    (wire.project / "out").mkdir(exist_ok=True)
    (wire.project / "out" / "RESULT.md").write_bytes(b"\x00\xffdone")
    status, kind, body = wire.call("GET", f"/v1/sessions/{THROWAWAY}/out/RESULT.md")
    assert (status, kind, body) == (200, "application/octet-stream", b"\x00\xffdone")
    status, kind, body = wire.call("GET", f"/v1/sessions/{THROWAWAY}/out")
    assert (status, kind, json.loads(body)) == (200, "application/json", {"files": [{"name": "RESULT.md", "bytes": 6}]})


def test_over_tls_an_over_long_body_is_413_and_the_server_keeps_serving(wire: Wire) -> None:
    status, _, body = wire.call("PUT", f"/v1/sessions/{THROWAWAY}/in/big", b"x" * 5000, 5000)
    assert (status, json.loads(body)) == (413, {"error": "too_large"})
    status, _, body = wire.call("PUT", f"/v1/sessions/{THROWAWAY}/in/big", b"", 10**9)
    assert (status, json.loads(body)) == (413, {"error": "too_large"})
    assert not (wire.project / "in" / "big").exists()
    assert wire.call("GET", "/v1/whoami")[0] == 200
