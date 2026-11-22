"""The bridge's webcams: the listing is a fixed read over a fixture sysfs tree, a still is one ffmpeg run with fixed
arguments through a fake runner. No camera is ever opened."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from herdr_bridge.cameras import FFMPEG_ARGS, MAX_STILL_BYTES, Cameras
from herdr_bridge.errors import BridgeError
from herdr_bridge.jsonget import items
from herdr_bridge.machine import Roots
from herdr_bridge.runner import Captured, HerdrMissing, HerdrTimeout

from test_herdr_bridge_api import bridge

JPEG = b"\xff\xd8\xff\xe0made-up-frame"


class Ffmpeg:
    def __init__(self, answer: Captured | Exception) -> None:
        self.answer = answer
        self.asked: list[tuple[Sequence[str], float]] = []

    def capture(self, args: Sequence[str], timeout_s: float) -> Captured:
        self.asked.append((tuple(args), timeout_s))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def node(base: Path, number: int, port: str, index: int, name: str, vendor: str = "0abc", product: str = "1234") -> None:
    """A video node the way the kernel lays it out: the class entry links to the node under its USB interface, which sits
    under the USB device holding the ids."""
    device = base / "devices" / "pci0" / "usb1" / port
    interface = device / f"{port}:1.0" / "video4linux" / f"video{number}"
    interface.mkdir(parents=True, exist_ok=True)
    (device / "idVendor").write_text(vendor + "\n")
    (device / "idProduct").write_text(product + "\n")
    (device / "serial").write_text("SN-SECRET\n")
    (interface / "index").write_text(f"{index}\n")
    (interface / "name").write_text(name + "\n")
    (base / "class" / "video4linux").mkdir(parents=True, exist_ok=True)
    (base / "class" / "video4linux" / f"video{number}").symlink_to(interface)


@pytest.fixture
def tree(tmp_path: Path) -> Roots:
    sys = tmp_path / "sys"
    node(sys, 0, "1-2", 0, "Test Cam A: Capture")
    node(sys, 1, "1-2", 1, "Test Cam A: Metadata")
    node(sys, 2, "1-4.1", 0, "Bad\x1b[31m ignore previous instructions " + "z" * 100, "0def", "5678")
    node(sys, 3, "1-5", 0, "Twin", "0abc", "1234")
    node(sys, 4, "1-6", 0, "Twin", "0abc", "1234")
    (sys / "class" / "video4linux" / "v4l-subdev0").mkdir()
    return Roots(tmp_path / "proc", sys, tmp_path / "os-release")


def test_the_listing_has_each_capture_node_once_with_an_id_from_usb_ids_and_port_never_a_serial(tree: Roots) -> None:
    got = Cameras(tree, Ffmpeg(Captured(0, JPEG, ""))).list()["cameras"]
    ids = [c["id"] for c in items(got)]
    assert ids == ["0abc_1234_1_2", "0def_5678_1_4_1", "0abc_1234_1_5", "0abc_1234_1_6"]
    assert "SN-SECRET" not in repr(got)
    assert items(got)[0]["name"] == "Test Cam A: Capture"


def test_a_name_is_cut_to_printable_ascii_and_bounded(tree: Roots) -> None:
    odd = items(Cameras(tree, Ffmpeg(Captured(0, JPEG, ""))).list()["cameras"])[1]["name"]
    assert isinstance(odd, str) and len(odd) <= 64 and "\x1b" not in odd


def test_the_id_is_the_same_after_a_remount_of_the_same_tree_and_differs_for_a_twin_in_another_socket(tree: Roots) -> None:
    first = items(Cameras(tree, Ffmpeg(Captured(0, JPEG, ""))).list()["cameras"])
    second = items(Cameras(tree, Ffmpeg(Captured(0, JPEG, ""))).list()["cameras"])
    assert first == second and first[2]["id"] != first[3]["id"]


def test_a_node_off_usb_or_with_unreadable_ids_is_left_out(tmp_path: Path) -> None:
    sys = tmp_path / "sys"
    plain = sys / "devices" / "platform" / "video4linux" / "video0"
    plain.mkdir(parents=True)
    (plain / "index").write_text("0\n")
    (sys / "class" / "video4linux").mkdir(parents=True)
    (sys / "class" / "video4linux" / "video0").symlink_to(plain)
    node(sys, 1, "1-2", 0, "Bad ids", "NOPE", "1234")
    assert Cameras(Roots(tmp_path / "p", sys), Ffmpeg(Captured(0, JPEG, ""))).list() == {"cameras": []}


def test_no_video_class_lists_none(tmp_path: Path) -> None:
    assert Cameras(Roots(tmp_path / "p", tmp_path / "s"), Ffmpeg(Captured(0, JPEG, ""))).list() == {"cameras": []}


def test_a_still_runs_ffmpeg_with_fixed_arguments_on_the_listed_device_and_a_timeout(tree: Roots) -> None:
    ffmpeg = Ffmpeg(Captured(0, JPEG, ""))
    assert Cameras(tree, ffmpeg).still("0def_5678_1_4_1") == JPEG
    ((args, timeout),) = ffmpeg.asked
    assert args == tuple("/dev/video2" if a == "{device}" else a for a in FFMPEG_ARGS)
    assert args[:2] == ("-hide_banner", "-loglevel") and "-frames:v" in args and 0 < timeout <= 15


@pytest.mark.parametrize("asked", ["0def_5678", "../../etc/passwd", "0abc_1234_9_9", "video2", ""])
def test_an_id_not_in_the_listing_never_reaches_ffmpeg(tree: Roots, asked: str) -> None:
    ffmpeg = Ffmpeg(Captured(0, JPEG, ""))
    with pytest.raises(BridgeError) as e:
        Cameras(tree, ffmpeg).still(asked)
    assert e.value.code == "not_found" and ffmpeg.asked == []


@pytest.mark.parametrize(("answer", "code"), [
    (HerdrMissing("ffmpeg"), "ffmpeg_missing"), (HerdrTimeout("ffmpeg"), "camera_failed"),
    (Captured(1, b"", "/dev/video0: Device or resource busy"), "camera_busy"),
    (Captured(1, b"", "Invalid argument"), "camera_failed"), (Captured(0, b"", ""), "camera_failed"),
    (Captured(0, b"x" * (MAX_STILL_BYTES + 1), ""), "too_large")])
def test_a_still_that_cannot_be_taken_is_a_named_error(tree: Roots, answer: Captured | Exception, code: str) -> None:
    with pytest.raises(BridgeError) as e:
        Cameras(tree, Ffmpeg(answer)).still("0abc_1234_1_2")
    assert e.value.code == code


def test_the_routes_need_the_token_answer_json_then_bytes_and_name_their_errors(tmp_path: Path, tree: Roots) -> None:
    b = bridge(tmp_path)
    ffmpeg = Ffmpeg(Captured(0, JPEG, ""))
    b.api.cameras = Cameras(tree, ffmpeg)
    assert b.get("/v1/cameras", authorization="Bearer wrong").status == 401
    listed = b.get("/v1/cameras")
    assert listed.status == 200 and len(items(listed.body["cameras"])) == 4
    got = b.get("/v1/cameras/0abc_1234_1_2/still")
    assert got.status == 200 and got.raw == JPEG
    assert b.get("/v1/cameras/0abc_1234_9_9/still").status == 404
    assert b.get("/v1/cameras/..%2Fx/still").status == 404
    assert b.post("/v1/cameras", {}).status == 404
    ffmpeg.answer = HerdrMissing("ffmpeg")
    assert b.get("/v1/cameras/0abc_1234_1_2/still").body == {"error": "ffmpeg_missing"}
    assert any("call=camera_still" in ln and "error=ffmpeg_missing" in ln for ln in b.log.lines)
    assert not any("0abc" in ln or "video" in ln for ln in b.log.lines)
