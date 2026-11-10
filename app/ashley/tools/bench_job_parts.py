"""What a worker is given of a bench: only the pieces a hand-off names (`Named`), each as a `Part` whose upload name is
made here from the piece id and its type, never from a title or a file's name. A stored piece goes as its text; a
large one as its bytes; with `run_files` its latest run's kept text files go too, and the artifacts it made (a model's
STL, 3MF and GLB) as bytes from the object store, `p<piece>-skipped.txt` naming what the run could not keep. A model
script's `inputs/<id>.*` meshes are other pieces and go only when named. Reads the bench as it is now."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .. import services
from ..errands.bench_jobs import Named
from ..errands.jobs_config import CONFIG, JobsConfig
from ..files.intake import key_of
from ..files.store import ObjectStore
from ..runs.model import Artifact, Output, Run
from ..runs.runs import Runs
from ..workshop import rules as workshop_rules, stored_file
from ..workshop.model import Owner
from ..workshop.rules import Rules
from ..workshop.workshop import Workshop

RULES = workshop_rules.load()
Origin = Literal["text", "stored", "run"]


class NoSuchPiece(Exception):
    """A named piece is not on the bench's layout: unknown, shelved, or another bench's."""

    def __init__(self, piece_id: int) -> None:
        super().__init__(str(piece_id))
        self.piece_id = piece_id


@dataclass(frozen=True)
class Part:
    """One file a worker gets: `name` as uploaded, `size` in bytes. `text` is a stored piece's body or a run file's
    text; `file` names a large piece's bytes in the object store. `title` and `piece_kind` are for the agent's prompt."""

    name: str
    piece_id: int
    origin: Origin
    size: int
    title: str
    piece_kind: str
    text: str | None = None
    file: stored_file.StoredFile | None = None


async def parts(owner: Owner, bench_id: int, named: tuple[Named, ...], config: JobsConfig = CONFIG,
                rules: Rules = RULES) -> tuple[Part, ...]:
    """The parts of `named`, in order. Raises NoSuchPiece, and what `Workshop.read` and `Runs.last_on_bench` raise."""
    view = await services.get(Workshop).read(owner, bench_id)
    by_id = {p.id: p for p in view.pieces}
    last: Mapping[int, Run] = {}
    if any(n.run_files for n in named):
        last = await services.get(Runs).last_on_bench(owner.household_id, bench_id)
    out: list[Part] = []
    for n in named:
        piece = by_id.get(n.piece_id)
        if piece is None:
            raise NoSuchPiece(n.piece_id)
        kind = rules.kinds.get(piece.kind)
        large = stored_file.file_of(piece.text.body) if kind is not None and kind.family == "large" else None
        if large is not None:
            ext = config.extensions.get(large.media_type, "bin")
            out.append(Part(f"p{piece.id}.{ext}", piece.id, "stored", large.size, piece.text.title, piece.kind, file=large))
        else:
            ext = config.kind_extensions.get(piece.kind, "txt")
            out.append(Part(f"p{piece.id}.{ext}", piece.id, "text", len(piece.text.body.encode()), piece.text.title,
                            piece.kind, text=piece.text.body))
        run = last.get(piece.id) if n.run_files else None
        if run is not None and run.output is not None:
            out.extend(_run_parts(piece.id, piece.text.title, piece.kind, run.output, run.artifacts, config))
    return tuple(out)


def _run_parts(piece_id: int, title: str, kind: str, output: Output, artifacts: Sequence[Artifact],
               config: JobsConfig) -> list[Part]:
    made: list[Part] = []
    for i, (original, text) in enumerate(sorted(output.files.items()), start=1):
        suffix = original.rsplit(".", 1)[-1].lower() if "." in original else ""
        ext = suffix if suffix.isascii() and suffix.isalnum() and len(suffix) <= 8 else "txt"
        stem = "run" if i == 1 else f"run{i}"
        made.append(Part(f"p{piece_id}-{stem}.{ext}", piece_id, "run", len(text.encode()), title, kind, text=text))
    used = {m.name for m in made}
    for artifact in sorted(artifacts, key=lambda a: a.name):
        name = _unused(f"p{piece_id}-{_stem(artifact.name)}", config.extensions.get(artifact.media_type, "bin"), used)
        used.add(name)
        stored = stored_file.StoredFile(artifact.sha256, artifact.size, artifact.media_type, artifact.name)
        made.append(Part(name, piece_id, "run", artifact.size, title, kind, file=stored))
    if output.skipped:
        text = "Files the latest run made that were not kept, so they are not here:\n" + "\n".join(output.skipped) + "\n"
        made.append(Part(f"p{piece_id}-skipped.txt", piece_id, "run", len(text.encode()), title, kind, text=text))
    return made


def _stem(name: str) -> str:
    """The artifact's own file stem cut to letters, digits, `_` and `-`; `artifact` when nothing is left."""
    stem = re.sub(r"[^A-Za-z0-9_-]", "", name.rsplit("/", 1)[-1].rsplit(".", 1)[0])[:32]
    return stem or "artifact"


def _unused(base: str, ext: str, used: set[str]) -> str:
    name, n = f"{base}.{ext}", 1
    while name in used:
        n += 1
        name = f"{base}-{n}.{ext}"
    return name


async def fetch(household_id: int, part: Part) -> bytes | None:
    """The bytes of `part`; None when a large piece's bytes are in no store."""
    if part.text is not None:
        return part.text.encode()
    assert part.file is not None
    return await services.get(ObjectStore).get(key_of(household_id, part.file.sha256))
