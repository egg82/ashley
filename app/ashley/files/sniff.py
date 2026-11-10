"""What a file is, judged from its bytes: the media type its signature names, else `text/plain` family for UTF-8 text
with no control characters, else nothing. The type the client declared is only checked against it (`Verdict`)."""

import io
import struct
import zipfile
from dataclasses import dataclass
from typing import Literal

from .config import FilesConfig, FileType

Why = Literal["type_not_allowed", "type_mismatch"]
GENERIC = ("", "application/octet-stream", "binary/octet-stream")
_PLAIN_CONTROLS = frozenset("\t\n\r\f")


@dataclass(frozen=True)
class Verdict:
    """`media_type` the file is, or None with `why` it is refused: `type_not_allowed` (no signature of the config and
    not text) or `type_mismatch` (the client named a type the config knows and the file is another)."""

    media_type: str | None
    why: Why | None = None


def sniff(data: bytes, declared: str, config: FilesConfig) -> Verdict:
    """The verdict for `data` that the client said was `declared` (a Content-Type, parameters allowed, or empty)."""
    said = declared.split(";")[0].strip().lower()
    found = _signature(data, config) or _text(data, said, config)
    if found is None:
        return Verdict(None, "type_not_allowed")
    if said not in GENERIC and config.knows(said) and said != found:
        return Verdict(None, "type_mismatch")
    return Verdict(found)


def _signature(data: bytes, config: FilesConfig) -> str | None:
    for kind in config.types:
        if all(data[offset:offset + len(want)] == want for offset, want in kind.magic) and _content(data, kind):
            return kind.media_type
    return None


def _content(data: bytes, kind: FileType) -> bool:
    """Whether `data` also holds what `kind` asks beyond its signature: the zip member, the size a binary STL's triangle
    count gives (at least one triangle)."""
    if kind.binary_stl:
        triangles = struct.unpack_from("<I", data, 80)[0] if len(data) >= 84 else 0
        return triangles > 0 and len(data) == 84 + 50 * triangles
    if kind.member is not None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                return kind.member in archive.namelist()
        except zipfile.BadZipFile:
            return False
    return True


def _text(data: bytes, said: str, config: FilesConfig) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(c) < 32 and c not in _PLAIN_CONTROLS or c == "\x7f" for c in text):
        return None
    return said if said in config.text_types else "text/plain"
