"""The existing models a model run starts with: the bench's file pieces that are an STL, a 3MF or a STEP, handed to the
run as binary inputs (`Job.inputs`, under `inputs/` in the pod) with an index of them, `inputs.json`, among its files,
which `ashley_cad.existing(piece_id)` reads. A file piece is named by its id, never by anything in the script. The
run may name the pieces it takes (`inputs`): exactly those are handed over, and one that is not a model file on the
bench, does not fit the language's `input_bytes` with the others named, or whose bytes the store cannot give refuses
the run (`InputRefused`). Without names every model file is a candidate, taken in layout order while the bytes fit;
one that does not fit, or cannot be read, is in the index's `left_out` with why, so the script's failure names it."""

import json
import logging
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from .. import logs, services
from ..files.intake import key_of
from ..files.store import ObjectStore, StoreUnavailable
from .model import Piece
from .rules import Rules
from .stored_file import StoredFile, file_of

log = logging.getLogger("ashley.workshop")
NAME = "inputs.json"
MEDIA = {".stl": ("model/stl", "text/plain"), ".3mf": ("model/3mf",), ".step": ("text/plain",), ".stp": ("text/plain",)}
"""Each suffix an existing model may have, with the media types its bytes may have been judged to be (an ASCII STL and
a STEP file are text)."""


class InputRefused(Exception):
    """A piece named as an input cannot be handed over: `why` is `missing` (not on the bench), `not_model` (not an STL,
    3MF or STEP file piece), `too_large` (it does not fit `input_bytes` with the ones named before it) or `unavailable`
    (the store cannot give its bytes); `sizes` says, for `too_large`, the bytes of the pieces named up to and including
    it against `input_bytes`."""

    def __init__(self, piece: int, why: Literal["missing", "not_model", "too_large", "unavailable"],
                 sizes: str = "") -> None:
        super().__init__(f"{piece}: {why}")
        self.piece = piece
        self.sizes = sizes
        self.why: Literal["missing", "not_model", "too_large", "unavailable"] = why


@dataclass(frozen=True)
class ModelInputs:
    """`blobs` (name -> bytes) are the files to hand over, `index` the text of `inputs.json`; both empty when the bench
    has no file piece of these kinds."""

    blobs: Mapping[str, bytes] = field(default_factory=dict[str, bytes])
    index: str | None = None


def importable(piece: Piece, rules: Rules) -> StoredFile | None:
    """The stored file of `piece` when it is a file piece named like an STL, 3MF or STEP and judged to be one."""
    kind = rules.kinds.get(piece.kind)
    if kind is None or kind.family != "large" or kind.format != "file":
        return None
    file = file_of(piece.text.body)
    allowed = MEDIA.get(PurePosixPath(file.name).suffix.lower()) if file is not None else None
    return file if file is not None and allowed is not None and file.media_type in allowed else None


def _candidates(pieces: Iterable[Piece], rules: Rules, named: Collection[int] | None) -> list[tuple[Piece, StoredFile]]:
    """The model files to hand over in layout order: every one, or only those in `named`, raising InputRefused for a
    named piece that is not one."""
    on_bench = {piece.id: piece for piece in pieces}
    files = {pid: file for pid, piece in on_bench.items() if (file := importable(piece, rules)) is not None}
    for pid in sorted(set(named or ())):
        if pid not in files:
            raise InputRefused(pid, "not_model" if pid in on_bench else "missing")
    return [(on_bench[pid], file) for pid, file in files.items() if named is None or pid in named]


async def inputs_of(household_id: int, pieces: Iterable[Piece], rules: Rules, input_bytes: int,
                    named: Collection[int] | None = None) -> ModelInputs:
    """The inputs for a run on a bench with `pieces`, at most `input_bytes` of them: every model file, or with `named`
    only those pieces (an empty `named` is none), which raises InputRefused instead of leaving one out. Logs
    `workshop.model_inputs` with the counts of those handed over and left out and their bytes."""
    items: list[dict[str, Any]] = []
    left_out: list[dict[str, Any]] = []
    blobs: dict[str, bytes] = {}
    used = 0
    for piece, file in _candidates(pieces, rules, named):
        if used + file.size > input_bytes:
            _leave(left_out, piece, file, "too_large", named, f"{used + file.size} bytes against {input_bytes}")
            continue
        data = await _bytes(household_id, file)
        if data is None:
            _leave(left_out, piece, file, "unavailable", named)
            continue
        used += len(data)
        name = f"{piece.id}{PurePosixPath(file.name).suffix.lower()}"
        blobs[name] = data
        items.append({"piece": piece.id, "name": file.name, "file": f"inputs/{name}", "size": len(data),
                      "sha256": file.sha256})
    if not items and not left_out:
        return ModelInputs()
    logs.info(log, "workshop.model_inputs", household=household_id, handed=len(items), left_out=len(left_out), bytes=used)
    return ModelInputs(blobs, json.dumps({"items": items, "left_out": left_out}, separators=(",", ":")))


def _leave(left_out: list[dict[str, Any]], piece: Piece, file: StoredFile, why: Literal["too_large", "unavailable"],
           named: Collection[int] | None, sizes: str = "") -> None:
    if named is not None:
        raise InputRefused(piece.id, why, sizes)
    left_out.append({"piece": piece.id, "name": file.name, "why": why})


async def _bytes(household_id: int, file: StoredFile) -> bytes | None:
    try:
        return await services.get(ObjectStore).get(key_of(household_id, file.sha256))
    except StoreUnavailable:
        return None
