"""What the object store takes and hands out, data in `files.json` beside this module:
- `max_bytes`, the largest file taken (one is read into memory whole);
- `link_ttl_s`, how long a download link lives at most (`links`);
- `repair_interval_s`, how often the repair singleton compares the copies (`repair`);
- `sweep_interval_s`, how often the sweep singleton looks for bytes no piece names, and `sweep_grace_s`, how old bytes
  must be before it may delete them (`sweep`);
- `types`, each media type a file may be, as signatures: every `[offset, hex]` pair of its `magic` must match the
  file's bytes at that offset; `image` says the page may show it in place; an optional `piece` (`clip` or `audio`) names
  the kind of piece a player shows it as; an optional `member` is a name a zip must also hold, and `binary_stl` says the
  file's size must be what its triangle count gives (a type that has it needs no signature). The first type whose
  signature and checks all hold names the file;
- `text_types`, the media types of a file that has no signature and is UTF-8 text, which a client may name for its
  own (anything else text is `text/plain`)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

FILE = Path(__file__).with_name("files.json")


@dataclass(frozen=True)
class FileType:
    media_type: str
    image: bool
    magic: tuple[tuple[int, bytes], ...]
    piece: Literal["clip", "audio"] | None = None
    member: str | None = None
    binary_stl: bool = False


@dataclass(frozen=True)
class FilesConfig:
    max_bytes: int
    link_ttl_s: int
    repair_interval_s: int
    sweep_interval_s: int
    sweep_grace_s: int
    types: tuple[FileType, ...]
    text_types: tuple[str, ...]

    def is_image(self, media_type: str) -> bool:
        return any(t.image and t.media_type == media_type for t in self.types)

    def plays(self, media_type: str) -> bool:
        """Whether a player shows `media_type`: a video or an audio file."""
        return any(t.piece is not None and t.media_type == media_type for t in self.types)

    def piece_kind(self, media_type: str) -> str:
        """The kind of large piece for bytes of `media_type`: `image`, `clip`, `audio`, else `file`."""
        for t in self.types:
            if t.media_type == media_type:
                return "image" if t.image else t.piece or "file"
        return "file"

    def knows(self, media_type: str) -> bool:
        return media_type in self.text_types or any(t.media_type == media_type for t in self.types)


def load() -> FilesConfig:
    """The tunables shipped in `files.json`. Raises ValueError as `parse`."""
    return parse(json.loads(FILE.read_text()))


def parse(data: object) -> FilesConfig:
    """A FilesConfig from parsed JSON. Raises ValueError for a missing or unknown key, a count that is not a positive
    integer, a signature that is not offset and hex, or a text type that is not a `type/subtype`."""
    raw = _object(data, "files config")
    names = {"max_bytes", "link_ttl_s", "repair_interval_s", "sweep_interval_s", "sweep_grace_s", "types", "text_types"}
    if set(raw) != names:
        raise ValueError(f"files config keys are {sorted(names)}")
    counts = [_count(raw[n], n) for n in
              ("max_bytes", "link_ttl_s", "repair_interval_s", "sweep_interval_s", "sweep_grace_s")]
    return FilesConfig(counts[0], counts[1], counts[2], counts[3], counts[4],
                       tuple(_type(t) for t in _list(raw["types"], "types")),
                       tuple(_text(t) for t in _list(raw["text_types"], "text_types")))


def _object(data: object, what: str) -> dict[str, object]:
    loose: Any = data
    if not isinstance(data, dict):
        raise ValueError(f"{what} is an object")
    return {str(k): v for k, v in dict[object, object](loose).items()}


def _list(data: object, what: str) -> list[object]:
    loose: Any = data
    if not isinstance(data, list) or not data:
        raise ValueError(f"{what} is a non-empty list")
    return list[object](loose)


def _count(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name}: expected a positive integer")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or value.count("/") != 1 or value != value.lower() or not value.strip():
        raise ValueError("a text type is a lower-case type/subtype")
    return value


def _type(entry: object) -> FileType:
    raw = _object(entry, "a type")
    image, piece, member, stl = raw.get("image"), raw.get("piece"), raw.get("member"), raw.get("binary_stl", False)
    if (not {"media_type", "image", "magic"} <= set(raw) <= {"media_type", "image", "magic", "piece", "member", "binary_stl"}
            or not isinstance(image, bool) or piece not in (None, "clip", "audio") or (image and piece)
            or not isinstance(stl, bool) or not (member is None or isinstance(member, str) and member)):
        raise ValueError("a type has media_type, image and magic, and for a player piece (not an image) clip or audio, "
                         "and optionally a zip member name and binary_stl")
    magic = raw["magic"]
    signatures = () if stl and magic == [] else tuple(_signature(m) for m in _list(magic, "magic"))
    return FileType(_text(raw["media_type"]), image, signatures,
                    "clip" if piece == "clip" else "audio" if piece == "audio" else None, member, stl)


def _signature(pair: object) -> tuple[int, bytes]:
    items = _list(pair, "a signature")
    if len(items) != 2:
        raise ValueError("a signature is [offset, hex]")
    offset, text = items
    if type(offset) is not int or offset < 0 or not isinstance(text, str) or not text:
        raise ValueError("a signature is [offset, hex]")
    return offset, bytes.fromhex(text)
