"""What this machine can do, read live for each `GET /v1/machine`. Every probe is a fixed read: a file under `/proc`,
`/sys` or `/etc/os-release`, `shutil.which` for each name in the configured bench tools (looked up, never run), and
`nvidia-smi` with fixed arguments and a short timeout. Nothing here takes a command from a caller or the config, and
no serial number, file content or environment value is read. A value a probe could not read is `None`, not zero."""

import os
import re
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path

from .runner import HerdrMissing, HerdrTimeout, Runner, SubprocessRunner

DEFAULT_TOOLS = ("pio", "sigrok-cli", "podman", "docker", "python3")
TOOL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
GPU_ARGS = ("--query-gpu=name,memory.total", "--format=csv,noheader,nounits")
GPU_TIMEOUT_S = 5.0
ROOT_HUB_VENDOR = "1d6b"
PRODUCT_CHARS = 64


@dataclass(frozen=True)
class Roots:
    """Where the kernel's files are; tests point these at a fixture tree."""

    proc: Path = Path("/proc")
    sys: Path = Path("/sys")
    os_release: Path = Path("/etc/os-release")


def read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def os_name(roots: Roots) -> str | None:
    for line in (read(roots.os_release) or "").splitlines():
        key, _, value = line.partition("=")
        if key == "PRETTY_NAME" and value.strip("\"'"):
            return value.strip("\"'")[:PRODUCT_CHARS]
    return None


def cpu(roots: Roots) -> dict[str, object]:
    info = read(roots.proc / "cpuinfo") or ""
    models = [v.strip() for k, _, v in (ln.partition(":") for ln in info.splitlines()) if k.strip() == "model name"]
    cores = sum(1 for ln in info.splitlines() if ln.partition(":")[0].strip() == "processor")
    return {"model": models[0] if models else None, "cores": cores or os.cpu_count()}


def megabytes(meminfo: str, key: str) -> int | None:
    for line in meminfo.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if name == key and len(parts) == 2 and parts[1] == "kB" and parts[0].isdigit():
            return int(parts[0]) // 1024
    return None


def memory(roots: Roots) -> dict[str, object]:
    meminfo = read(roots.proc / "meminfo") or ""
    return {"total_mb": megabytes(meminfo, "MemTotal"), "available_mb": megabytes(meminfo, "MemAvailable")}


def printable(raw: str | None) -> str | None:
    """A device's own words, cut to printable ASCII of bounded length: it is text a device chose, not the owner."""
    if raw is None:
        return None
    clean = "".join(c for c in raw.strip() if " " <= c <= "~")[:PRODUCT_CHARS]
    return clean or None


def usb(roots: Roots) -> list[dict[str, object]] | None:
    """Each USB device by `vendor:product` id and its product string (never a serial number), root hubs left out;
    None when the bus cannot be listed."""
    base = roots.sys / "bus" / "usb" / "devices"
    try:
        names = sorted(p.name for p in base.iterdir())
    except OSError:
        return None
    found: list[dict[str, object]] = []
    for name in names:
        vendor, product = read(base / name / "idVendor"), read(base / name / "idProduct")
        if vendor is None or product is None or vendor.strip() == ROOT_HUB_VENDOR:
            continue
        ident = f"{vendor.strip()}:{product.strip()}"
        if re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{4}", ident):
            found.append({"id": ident, "product": printable(read(base / name / "product"))})
    return found


def tools_present(names: tuple[str, ...]) -> list[str]:
    return [n for n in names if shutil.which(n) is not None]


class Machine:
    def __init__(self, tools: tuple[str, ...] = DEFAULT_TOOLS, roots: Roots = Roots(),
                 gpu: Runner | None = None) -> None:
        self.tools = tools
        self.roots = roots
        self.gpu = gpu or SubprocessRunner("nvidia-smi")

    def gpus(self) -> list[dict[str, object]] | None:
        """The GPUs `nvidia-smi` lists; none when it is not installed; None (unknown) when it failed or timed out."""
        try:
            done = self.gpu.run(GPU_ARGS, GPU_TIMEOUT_S)
        except HerdrMissing:
            return []
        except HerdrTimeout:
            return None
        if done.code != 0:
            return None
        found: list[dict[str, object]] = []
        for line in done.out.splitlines():
            name, _, size = line.rpartition(",")
            if name.strip():
                found.append({"model": printable(name), "memory_mb": int(size) if size.strip().isdigit() else None})
        return found

    def report(self, busy: bool | None) -> dict[str, object]:
        """`busy` is whether a session is working (None when herdr could not say)."""
        return {"hostname": socket.gethostname(), "os": os_name(self.roots),
                "kernel": (read(self.roots.proc / "sys" / "kernel" / "osrelease") or "").strip() or None,
                "cpu": cpu(self.roots), "memory": memory(self.roots), "gpus": self.gpus(), "busy": busy,
                "tools": tools_present(self.tools), "usb": usb(self.roots)}
