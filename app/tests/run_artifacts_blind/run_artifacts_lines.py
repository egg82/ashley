"""The runner's line and the envelope's input for the blind run-artifact tests: files packed as a line carries them,
hand-built marked lines, and the line the runner prints for a working directory."""

import base64
import hashlib
import json
import zlib
from collections.abc import Mapping
from pathlib import Path

from ashley.runs import runner


def packed(data: bytes) -> str:
    """How a line carries a file: base64 of its deflated bytes."""
    return base64.b64encode(zlib.compress(data)).decode()


def packed_zeros(size: int) -> str:
    """`size` zero bytes as a line carries them, deflated a megabyte at a time so the test never holds them whole."""
    deflater = zlib.compressobj(9)
    chunk = b"\x00" * (1 << 20)
    parts = [deflater.compress(chunk) for _ in range(size >> 20)]
    parts.append(deflater.flush())
    return base64.b64encode(b"".join(parts)).decode()


def line_of(artifacts: object = None, stdout: str = "", exit_code: int = 0) -> str:
    """A marked line as a pod's log ends in, built by hand; `artifacts` is name -> what the line holds for it."""
    body: dict[str, object] = {"exit_code": exit_code, "timed_out": False, "stdout": stdout, "stderr": "", "cut": False,
                               "files": {}, "skipped": []}
    if artifacts is not None:
        body["artifacts"] = artifacts
    return runner.MARK + json.dumps(body)


def pod_line(tmp_path: Path, artifacts: Mapping[str, bytes], text: Mapping[str, str] | None = None,
             limits: Mapping[str, int] | None = None, stdout: str = "") -> str:
    """The line the runner prints for a working directory holding these files, under these limits."""
    work, out = tmp_path / "work", tmp_path / "out"
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(exist_ok=True)
    (out / "stdout").write_bytes(stdout.encode())
    (out / "stderr").write_bytes(b"")
    for name, data in artifacts.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_bytes(data)
    for name, body in (text or {}).items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(body)
    return runner.line(0, False, out, work, dict(limits or CAD_LIMITS))


CAD_LIMITS: dict[str, int] = {"timeout_s": 60, "output_chars": 8000, "file_chars": 20000, "max_files": 16,
                              "log_bytes": 8388608, "artifact_bytes": 16777216}
PY_LIMITS: dict[str, int] = {k: v for k, v in CAD_LIMITS.items() if k != "artifact_bytes"} | {"log_bytes": 262144}


def noise(size: int, seed: str = "n") -> bytes:
    """`size` bytes that do not deflate."""
    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(f"{seed}{counter}".encode()).digest()
        counter += 1
    return bytes(out[:size])
