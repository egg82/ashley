"""The machine's webcams: the listing is a fixed read of `/sys/class/video4linux`, and a still is one `ffmpeg` run with
fixed arguments. Nothing here takes a command, a path or an argument from a caller: a caller's camera id is looked up in
the listing and only the device number it maps to reaches `ffmpeg`.

A camera usually shows the kernel two nodes, one that captures video and one that carries metadata. The capture node is
the one whose `index` file reads 0 (the first node a driver registers for a device); the others are left out. Only
cameras on USB are listed, since their id is built from the USB `vendor:product` and the port's sysfs path
(`046d_0825_3_3` for the device on port `3-3`): it survives a reboot with the camera in the same socket, differs for two
identical cameras in two sockets, and is never a serial number."""

import re
from dataclasses import dataclass
from pathlib import Path

from .errors import BridgeError
from .machine import Roots, printable, read
from .runner import Capturer, HerdrMissing, HerdrTimeout, SubprocessCapturer

NODE = re.compile(r"video(\d+)")
HEX4 = re.compile(r"[0-9a-f]{4}")
CAMERA_ID = r"[0-9a-f]{4}_[0-9a-f]{4}_[0-9_]+"
STILL_TIMEOUT_S = 10.0
MAX_STILL_BYTES = 4 * 1024 * 1024
FFMPEG_ARGS = ("-hide_banner", "-loglevel", "error", "-nostdin", "-f", "v4l2", "-i", "{device}", "-frames:v", "1",
               "-fs", str(MAX_STILL_BYTES), "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1")
BUSY = "busy"


@dataclass(frozen=True)
class Camera:
    id: str
    name: str
    device: str
    """The node `ffmpeg` opens, `/dev/video<N>`; never sent to a caller."""


def _usb_device(node: Path) -> Path | None:
    """The USB device directory (the one holding `idVendor`) above a video node's real path."""
    for parent in node.resolve().parents:
        if (parent / "idVendor").is_file():
            return parent
    return None


def listing(roots: Roots) -> list[Camera]:
    """The capture nodes on USB, by device number. A node whose files cannot be read is left out."""
    base = roots.sys / "class" / "video4linux"
    try:
        nodes = sorted((p for p in base.iterdir() if NODE.fullmatch(p.name)), key=lambda p: int(p.name[5:]))
    except OSError:
        return []
    found: list[Camera] = []
    for node in nodes:
        if (read(node / "index") or "").strip() != "0":
            continue
        usb = _usb_device(node)
        vendor, product = (read(usb / "idVendor"), read(usb / "idProduct")) if usb else (None, None)
        if usb is None or vendor is None or product is None:
            continue
        v, p = vendor.strip(), product.strip()
        if not (HEX4.fullmatch(v) and HEX4.fullmatch(p)):
            continue
        port = re.sub(r"[^0-9]", "_", usb.name)
        found.append(Camera(f"{v}_{p}_{port}", printable(read(node / "name")) or f"{v}:{p}", f"/dev/{node.name}"))
    return found


class Cameras:
    def __init__(self, roots: Roots = Roots(), ffmpeg: Capturer | None = None) -> None:
        self.roots = roots
        self.ffmpeg = ffmpeg or SubprocessCapturer("ffmpeg")

    def list(self) -> dict[str, object]:
        return {"cameras": [{"id": c.id, "name": c.name} for c in listing(self.roots)]}

    def still(self, camera_id: str) -> bytes:
        """One JPEG frame from the camera `camera_id` of the listing. `not_found` for an id not listed,
        `ffmpeg_missing`, `camera_busy` (another program holds the device), `camera_failed` (ffmpeg failed, timed out or
        gave nothing), `too_large` (a frame over the byte cap)."""
        camera = next((c for c in listing(self.roots) if c.id == camera_id), None)
        if camera is None:
            raise BridgeError("not_found")
        args = tuple(camera.device if a == "{device}" else a for a in FFMPEG_ARGS)
        try:
            done = self.ffmpeg.capture(args, STILL_TIMEOUT_S)
        except HerdrMissing as e:
            raise BridgeError("ffmpeg_missing") from e
        except HerdrTimeout as e:
            raise BridgeError("camera_failed") from e
        if done.code != 0:
            raise BridgeError("camera_busy" if "busy" in done.err.lower() else "camera_failed")
        if not done.data:
            raise BridgeError("camera_failed")
        if len(done.data) > MAX_STILL_BYTES:
            raise BridgeError("too_large")
        return done.data
