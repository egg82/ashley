"""What `python -m ashley.evals bench-replay` and `bench-replay-capture` run: the replay in a throwaway database made
beside `DATABASE_URL` (`scratch_db`), migrated, wired as the app is and dropped after (kept with `keep`), so the spend
ledger it reads its cost from is its own; and the capture, reading the database `DATABASE_URL` names."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection

from .. import services, wiring
from ..db.database import Database
from ..db.migrate import migrate
from ..settings import Settings
from ..tools import bench_replay_world as world
from . import bench_replay_capture, bench_replay_grader, scratch_db
from .bench_replay import Options, Result, replay, to_json
from .bench_replay_snapshot import load


async def run(settings: Settings, directory: Path, options: Options, events: Path | None, keep: bool,
              cad_image: str | None) -> Result:
    """Runs code in podman on this machine when `cad_image` is given, else in the wired sandbox. Raises
    FileNotFoundError when `directory` holds no snapshot."""
    snapshot, files = load(directory)
    lines = events.read_text().splitlines() if events is not None else []
    name, url = scratch_db.create(settings.database_url)
    closers: list[Callable[[], Coroutine[Any, Any, None]]] = []
    try:
        await asyncio.to_thread(migrate, url)
        closers = wiring.wire(replace(settings, database_url=url))
        database = services.get(Database)
        await database.open()
        if cad_image:
            world.local_sandbox(cad_image)
        try:
            return await replay(snapshot, files, url, bench_replay_grader.grade, options, lines)
        finally:
            await database.close()
    finally:
        for close in closers:
            await close()
        if not keep:
            scratch_db.drop(settings.database_url, name)


def write(result: Result, path: Path | None) -> str:
    """The result as JSON, written to `path` when given."""
    text = json.dumps(to_json(result), indent=1)
    if path is not None:
        path.write_text(text + "\n")
    return text


async def capture(settings: Settings, bench_id: int, from_turn: int, directory: Path) -> str:
    closers = wiring.wire(settings)
    try:
        async with await AsyncConnection.connect(settings.database_url) as conn:
            got = await bench_replay_capture.capture(conn, bench_id, from_turn, directory)
    finally:
        for close in closers:
            await close()
    return f"captured {len(got.commands)} commands, {len(got.turns)} turns, {len(got.asks())} asks into {directory}"
