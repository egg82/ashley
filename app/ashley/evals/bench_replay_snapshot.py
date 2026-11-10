"""A bench conversation captured for the bench replay (`bench_replay`): the bench's whole command log, the turns said on
the bench's own thread, her looks in the conversation and the bytes of its file pieces, written to a directory outside
the repository (a household's data never enters the tree) and read back from it.

`snapshot.json` holds everything but the bytes, which are `files/<sha256>`. An image piece whose bytes are over the
most a look is given whole (`tools.bench_look.CONFIG.max_image_bytes`) is re-encoded as a smaller JPEG with ffmpeg at
capture, and the commands that name it are rewritten to the new bytes, so `bench_look` shows her the picture itself as
a look pod's screenshot of it would have; `provenance.reencoded` maps each new sha256 to the one it replaced.

Times are seconds since the epoch. `from_turn` is the first person turn of the conversation replayed; `conversation_id`
is the conversation it opened."""

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

Author = Literal["person", "ashley", "household"]
FILE = "snapshot.json"


@dataclass(frozen=True)
class Command:
    """One bench command as logged: `by_person` when a person made it, `outside` the flag her change was made under."""

    seq: int
    at: float
    by_person: bool
    outside: bool
    command: dict[str, Any]
    outcome: str
    effect: dict[str, Any] | None


@dataclass(frozen=True)
class Said:
    """One turn on the bench's thread."""

    id: int
    conversation_id: int
    author: Author
    at: float
    follows: bool
    answers: int | None
    text: str
    source: str | None = None
    visibility: str = "private"


@dataclass(frozen=True)
class Look:
    """One look of hers: the person turn it was for, the piece (None for the whole bench) and when."""

    turn_id: int
    piece_id: int | None
    at: float


@dataclass(frozen=True)
class Snapshot:
    zone: str
    person: str
    bench_title: str
    work: str | None
    conversation_id: int
    from_turn: int
    commands: tuple[Command, ...]
    turns: tuple[Said, ...]
    looks: tuple[Look, ...]
    provenance: dict[str, Any] = field(default_factory=dict[str, Any])

    def asks(self) -> tuple[Said, ...]:
        """The turns of the replayed conversation she answers: the person's, and the household's on the bench's behalf."""
        return tuple(t for t in self.turns if t.conversation_id == self.conversation_id and t.author != "ashley")

    def before(self) -> tuple[Said, ...]:
        """The turns on the bench's thread before the replayed conversation."""
        return tuple(t for t in self.turns if t.id < self.from_turn)

    def first_at(self) -> float:
        return next(t.at for t in self.turns if t.id == self.from_turn)


def load(directory: Path) -> tuple[Snapshot, dict[str, bytes]]:
    """The snapshot in `directory` and the bytes of its files by sha256. Raises FileNotFoundError when it has none."""
    raw: dict[str, Any] = json.loads((directory / FILE).read_text())
    snapshot = Snapshot(
        raw["zone"], raw["person"], raw["bench_title"], raw.get("work"), raw["conversation_id"], raw["from_turn"],
        tuple(Command(**c) for c in raw["commands"]), tuple(Said(**t) for t in raw["turns"]),
        tuple(Look(**k) for k in raw["looks"]), raw.get("provenance", {}))
    files = {p.name: p.read_bytes() for p in (directory / "files").iterdir()} if (directory / "files").is_dir() else {}
    return snapshot, files


def write(directory: Path, snapshot: Snapshot, files: Mapping[str, bytes]) -> None:
    (directory / "files").mkdir(parents=True, exist_ok=True)
    for sha, data in files.items():
        (directory / "files" / sha).write_bytes(data)
    (directory / FILE).write_text(json.dumps(asdict(snapshot), indent=1, ensure_ascii=False) + "\n")


def object_of(value: object) -> dict[str, Any] | None:
    """`value` when it is a JSON object."""
    loose: Any = value
    return dict[str, Any](loose) if isinstance(value, dict) else None


def file_of(body: str) -> dict[str, Any] | None:
    """A file piece's stored body (`{"sha256", "size", "media_type", "name"}`), or None for any other body."""
    try:
        raw = object_of(json.loads(body))
    except ValueError:
        return None
    return raw if raw is not None and isinstance(raw.get("sha256"), str) else None


def reencoded(snapshot: Snapshot, files: dict[str, bytes], limit: int,
              shrink: "Shrink") -> tuple[Snapshot, dict[str, bytes]]:
    """`snapshot` and `files` with every JPEG or PNG over `limit` bytes made a JPEG of at most `limit` by `shrink`, and
    each command naming it rewritten to the new bytes."""
    swaps: dict[str, dict[str, Any]] = {}
    for sha, data in list(files.items()):
        if len(data) > limit and _is_picture(snapshot, sha):
            smaller = shrink(data, limit)
            new = _sha(smaller)
            files[new] = smaller
            del files[sha]
            swaps[sha] = {"sha256": new, "size": len(smaller), "media_type": "image/jpeg"}
    commands = tuple(_swapped(c, swaps) for c in snapshot.commands)
    made = {v["sha256"]: k for k, v in swaps.items()}
    return replace(snapshot, commands=commands, provenance={**snapshot.provenance, "reencoded": made}), files


def _is_picture(snapshot: Snapshot, sha: str) -> bool:
    for c in snapshot.commands:
        file = file_of(str(c.command.get("body", "")))
        if file is not None and file["sha256"] == sha:
            return str(file.get("media_type")) in ("image/jpeg", "image/png")
    return False


def _swapped(command: Command, swaps: Mapping[str, dict[str, Any]]) -> Command:
    """`command` with the file body of its own and of its effect's piece pointed at the bytes that replaced them."""
    made = dict(command.command)
    if isinstance(made.get("body"), str):
        made["body"] = _swap_body(made["body"], swaps)
    effect = None if command.effect is None else dict(command.effect)
    piece = None if effect is None else object_of(effect.get("piece"))
    if effect is not None and piece is not None and isinstance(piece.get("body"), str):
        effect["piece"] = {**piece, "body": _swap_body(piece["body"], swaps)}
    return replace(command, command=made, effect=effect)


def _swap_body(body: str, swaps: Mapping[str, dict[str, Any]]) -> str:
    file = file_of(body)
    return body if file is None or file["sha256"] not in swaps else json.dumps({**file, **swaps[file["sha256"]]})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Shrink:
    """Re-encodes a picture as a JPEG of at most `limit` bytes with ffmpeg: its long side at most 2048 pixels, then
    lower quality until it fits. Raises RuntimeError when ffmpeg is missing or nothing fits."""

    def __call__(self, data: bytes, limit: int) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / "in", Path(tmp) / "out.jpg"
            source.write_bytes(data)
            for quality in (3, 5, 8, 12, 18):
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(source), "-vf",
                                "scale='min(2048,iw)':'min(2048,ih)':force_original_aspect_ratio=decrease",
                                "-q:v", str(quality), str(out)], check=True)
                if out.stat().st_size <= limit:
                    return out.read_bytes()
        raise RuntimeError("no quality made the picture small enough")
