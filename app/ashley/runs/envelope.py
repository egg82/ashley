"""Reading the runner's last line (`runner.MARK` then JSON) out of a pod's log. The script can print that line too,
so everything in it is checked and cut to the limits again here, as the script's own output would be."""

import base64
import binascii
import json
import zlib
from pathlib import Path
from typing import Any

from .config import RunsConfig
from .loose import as_list, as_object
from .model import Output
from .runner import ARTIFACT_SUFFIXES, MARK, placed


def parse(log_text: str, config: RunsConfig, artifact_bytes: int = 0) -> Output | None:
    """The output the log's last marked line reports, or None when there is no such line or it is malformed. Binary
    files are read only when `artifact_bytes`, the language's budget, is above 0."""
    lines = [line for line in log_text.split("\n") if line.startswith(MARK)]
    if not lines:
        return None
    try:
        raw = as_object(json.loads(lines[-1][len(MARK):]))
    except ValueError:
        return None
    return None if raw is None else _output(raw, config, artifact_bytes)


def _output(raw: dict[str, Any], config: RunsConfig, artifact_bytes: int) -> Output | None:
    exit_code, timed_out = raw.get("exit_code"), raw.get("timed_out")
    stdout, stderr = raw.get("stdout"), raw.get("stderr")
    if not isinstance(stdout, str) or not isinstance(stderr, str) or not isinstance(timed_out, bool):
        return None
    if timed_out == (type(exit_code) is int) or not (exit_code is None or type(exit_code) is int):
        return None
    files, skipped = _files(raw.get("files"), raw.get("skipped"), config)
    artifacts, skipped = _artifacts(raw.get("artifacts"), skipped, artifact_bytes, config.max_files) \
        if artifact_bytes else ({}, skipped)
    limit = config.output_chars
    cut = raw.get("cut") is True or len(stdout) > limit or len(stderr) > limit
    code = exit_code if type(exit_code) is int else None
    return Output("timed_out" if timed_out else "ran", code, stdout[:limit], stderr[:limit], cut, files, skipped, artifacts)


def _files(files: object, skipped: object, config: RunsConfig) -> tuple[dict[str, str], tuple[str, ...]]:
    kept: dict[str, str] = {}
    left: list[str] = [s for s in as_list(skipped) or [] if isinstance(s, str)]
    for name, text in (as_object(files) or {}).items():
        if isinstance(text, str):
            if len(kept) >= config.max_files or len(text) > config.file_chars:
                left.append(name)
            else:
                kept[name] = text
    return kept, tuple(left)


def _artifacts(found: object, skipped: tuple[str, ...], budget: int, max_files: int) -> tuple[dict[str, bytes], tuple[str, ...]]:
    """The binary files the line carries (name -> base64 of deflated bytes) that are plain names ending in an artifact
    suffix, inflate to no more than `budget` bytes together, and are no more than `max_files`; the rest are named in
    the skipped names."""
    kept: dict[str, bytes] = {}
    left = list(skipped)
    used = 0
    for name, text in (as_object(found) or {}).items():
        data = _inflated(text, budget - used) if len(kept) < max_files and _plain(name) else None
        if data is None:
            left.append(name)
        else:
            kept[name] = data
            used += len(data)
    return kept, tuple(left)


def _plain(name: str) -> bool:
    return name.endswith(ARTIFACT_SUFFIXES) and placed(Path("/"), name) is not None


def _inflated(text: object, room: int) -> bytes | None:
    """The bytes `text` (base64 of zlib) holds, None when it is neither or inflates past `room`."""
    if not isinstance(text, str):
        return None
    try:
        inflater = zlib.decompressobj()
        data = inflater.decompress(base64.b64decode(text, validate=True), room + 1)
    except (binascii.Error, zlib.error):
        return None
    return data if len(data) <= room and inflater.eof and data else None
