"""Taking a file in: size, content and name judged, then kept in the object store under its household and its sha256.
The same path for a person's upload and for a file she makes. The bytes of a file are never logged, nor its name."""

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

from .. import logs, services
from .config import FilesConfig
from .sniff import sniff
from .store import ObjectStore

log = logging.getLogger("ashley.files")
PREFIX = "bench/"
Reason = Literal["empty", "too_large", "type_not_allowed", "type_mismatch"]
NAME_CHARS = 200
_CONTROLS = re.compile(r"[\x00-\x1f\x7f]")


class Refused(Exception):
    """The file is not taken, for `reason`; nothing was stored."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


@dataclass(frozen=True)
class Stored:
    """A file kept: its `sha256` and `size`, the `media_type` its bytes are, and the `name` it goes by (no directory,
    no control characters, at most `NAME_CHARS`)."""

    sha256: str
    size: int
    media_type: str
    name: str


def key_of(household_id: int, sha256: str) -> str:
    """Where a file's bytes are: under its household, so the same bytes of two households are two objects and a link
    to one reaches only that household's."""
    return f"{PREFIX}{household_id}/{sha256}"


def name_of(raw: str) -> str:
    """`raw`, percent-decoded, as a plain file name: what follows the last `/` or `\\`, control characters dropped,
    trimmed and cut; `file` when nothing is left."""
    last = re.split(r"[\\/]", unquote(raw))[-1]
    return _CONTROLS.sub("", last).strip()[:NAME_CHARS].strip() or "file"


async def take(household_id: int, data: bytes, raw_name: str, declared: str, config: FilesConfig) -> Stored:
    """Judge `data` and keep it. Raises Refused (`empty`, `too_large`, `type_not_allowed`, and `type_mismatch` when
    `declared` names a type the config knows and the bytes are another) and StoreUnavailable. Logs `files.stored`
    with the household, size, media type, copies and duration."""
    started = time.monotonic()
    if not data:
        raise Refused("empty")
    if len(data) > config.max_bytes:
        raise Refused("too_large")
    verdict = sniff(data, declared, config)
    if verdict.media_type is None:
        assert verdict.why is not None
        logs.info(log, "files.refused", household=household_id, size=len(data), reason=verdict.why)
        raise Refused(verdict.why)
    sha = hashlib.sha256(data).hexdigest()
    copies = await services.get(ObjectStore).put(key_of(household_id, sha), data)
    logs.info(log, "files.stored", household=household_id, size=len(data), media_type=verdict.media_type,
              copies=copies, ms=int((time.monotonic() - started) * 1000))
    return Stored(sha, len(data), verdict.media_type, name_of(raw_name))
