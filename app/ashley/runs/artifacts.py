"""Keeping a bench run's binary outputs: each artifact the sandbox brought back is judged by its bytes and stored as any
file is (`ashley.files.intake.take`), and the run records what was kept. Bytes and names are people's data and are never
logged."""

import logging
from dataclasses import replace
from pathlib import PurePosixPath

from .. import logs
from ..files import config as files_config
from ..files.config import FilesConfig
from ..files.intake import Refused, take
from ..files.store import StoreUnavailable
from .model import Artifact, NewRun, Output

log = logging.getLogger("ashley.runs")
FILES = files_config.load()
TYPES = {".glb": "model/gltf-binary", ".stl": "model/stl", ".3mf": "model/3mf"}
"""The media type each artifact suffix (`runner.ARTIFACT_SUFFIXES`) must have by its bytes."""


async def keep(new: NewRun, run_id: int, output: Output, config: FilesConfig = FILES) -> tuple[Output, tuple[Artifact, ...]]:
    """`output` without its artifacts' bytes, and the artifacts kept. Only a bench run keeps any. One the files judge not
    to be what its suffix says, or that the store cannot take (after the first of those, none is tried), is named in
    `skipped` instead. Logs `runs.artifacts` with the run and counts for a bench run whose output had any."""
    if not output.artifacts:
        return output, ()
    if new.bench is None:
        return replace(output, artifacts={}, skipped=(*output.skipped, *sorted(output.artifacts))), ()
    kept: list[Artifact] = []
    unkept: list[str] = []
    store_down = False
    for name, data in sorted(output.artifacts.items()):
        if store_down:
            unkept.append(name)
            continue
        try:
            stored = await take(new.household_id, data, name, TYPES[PurePosixPath(name).suffix.lower()], config)
        except Refused as e:
            logs.warning(log, "runs.artifact_dropped", run=run_id, reason=e.reason)
            unkept.append(name)
        except StoreUnavailable:
            logs.warning(log, "runs.artifact_dropped", run=run_id, reason="store_unavailable")
            unkept.append(name)
            store_down = True
        else:
            kept.append(Artifact(name, stored.sha256, stored.size, stored.media_type))
    logs.info(log, "runs.artifacts", run=run_id, kept=len(kept), dropped=len(unkept), bytes=sum(a.size for a in kept))
    return replace(output, artifacts={}, skipped=(*output.skipped, *unkept)), tuple(kept)
