"""The body of the `image` and `file` kinds (family `large`): the bytes live in the object store (`ashley.files`), the
body names them. One JSON object of exactly `sha256` (64 lower-case hex digits, the bytes' hash), `size` (their length,
at least 1), `media_type` (what the bytes were judged to be, `type/subtype`) and `name` (the file name, at most
`MAX_NAME` characters). A body is never empty: a file piece is made from bytes. The object is
`ashley.files.intake.key_of(household, sha256)`. The body of a large piece is fixed once the piece is made; an Edit may
change its title and nothing else (`decide`)."""

import json
import re
from dataclasses import dataclass

from .automation_config import object_of

MAX_NAME = 200
_FIELDS: frozenset[str] = frozenset(("sha256", "size", "media_type", "name"))
_SHA = re.compile(r"[0-9a-f]{64}")
_MEDIA = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


@dataclass(frozen=True)
class StoredFile:
    """A large piece's body, understood."""

    sha256: str
    size: int
    media_type: str
    name: str


def body_of(file: StoredFile) -> str:
    return json.dumps({"sha256": file.sha256, "size": file.size, "media_type": file.media_type, "name": file.name},
                      ensure_ascii=False, separators=(",", ":"))


def file_of(body: str) -> StoredFile | None:
    """The file `body` names, None when it is not a body of the shape above."""
    try:
        raw = object_of(json.loads(body))
    except ValueError:
        return None
    if raw is None or frozenset(raw) != _FIELDS:
        return None
    sha, size, media, name = raw["sha256"], raw["size"], raw["media_type"], raw["name"]
    if (not isinstance(sha, str) or not _SHA.fullmatch(sha) or type(size) is not int or size < 1
            or not isinstance(media, str) or not _MEDIA.fullmatch(media)
            or not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME):
        return None
    return StoredFile(sha, size, media, name)


def file_well_formed(body: str) -> bool:
    return file_of(body) is not None


def image_well_formed(body: str) -> bool:
    """A file body whose media type is an image."""
    return _of_type(body, "image/")


def clip_well_formed(body: str) -> bool:
    """A file body whose media type is a video's."""
    return _of_type(body, "video/")


def audio_well_formed(body: str) -> bool:
    """A file body whose media type is an audio file's."""
    return _of_type(body, "audio/")


def _of_type(body: str, prefix: str) -> bool:
    file = file_of(body)
    return file is not None and file.media_type.startswith(prefix)
