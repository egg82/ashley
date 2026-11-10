"""`python -m ashley.evals bench-replay-capture --bench N --from-turn T DIR`: write a bench replay snapshot
(`bench_replay_snapshot`) of bench N, from the conversation person turn T opened, into DIR. Reads the database
`DATABASE_URL` names (point it at production with a read-only session) and that database's object store (`FILES_*`)
for the bytes of the bench's file pieces; writes nothing but DIR. Logs `eval.bench_replay_capture` with the bench,
counts and duration_ms."""

import logging
import time
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection

from .. import logs
from ..tools import bench_replay_world as world
from ..tools.bench_look import CONFIG as LOOKS
from . import bench_replay_rows as rows
from .bench_replay_snapshot import Command, Shrink, Snapshot, file_of, reencoded, write

log = logging.getLogger("ashley.evals")


async def capture(conn: AsyncConnection[Any], bench_id: int, from_turn: int, directory: Path) -> Snapshot:
    """Raises ValueError when the bench or the turn is not found, or the turn is not on the bench's thread."""
    started = time.perf_counter()
    head = await (await conn.execute(
        "SELECT b.household_id, b.title, b.work, h.timezone, p.name, t.conversation_id FROM benches b "
        "JOIN households h ON h.id = b.household_id JOIN people p ON p.id = b.owner_id "
        "JOIN turns t ON t.id = %s AND t.household_id = b.household_id "
        "JOIN conversations c ON c.id = t.conversation_id AND c.thread = 'bench:' || b.id WHERE b.id = %s",
        (from_turn, bench_id))).fetchone()
    if head is None:
        raise ValueError(f"no bench {bench_id} with turn {from_turn} on its thread")
    household, title, work, zone, person, conversation = head
    commands = await rows.commands(conn, bench_id)
    snapshot = Snapshot(zone, person, _first_title(commands, title), work, conversation, from_turn, commands,
                        await rows.turns(conn, household, bench_id, 0, conversation),
                        await rows.looks(conn, bench_id, conversation),
                        {"bench_id": bench_id, "household_id": household})
    files = {sha: data for sha in _shas(commands)
             if (data := await world.file_bytes(household, sha)) is not None}
    snapshot, files = reencoded(snapshot, files, LOOKS.max_image_bytes, Shrink())
    write(directory, snapshot, files)
    logs.info(log, "eval.bench_replay_capture", bench=bench_id, commands=len(commands), turns=len(snapshot.turns),
              files=len(files), duration_ms=int((time.perf_counter() - started) * 1000))
    return snapshot


def _first_title(commands: tuple[Command, ...], current: str) -> str:
    """The title the bench opened with: the first rename's `before`, else the title it has."""
    for c in commands:
        if c.effect is not None and c.effect.get("type") == "renamed":
            return str(c.effect["before"])
    return current


def _shas(commands: tuple[Command, ...]) -> list[str]:
    found: list[str] = []
    for c in commands:
        file = file_of(str(c.command.get("body", ""))) if c.command.get("type") == "add" else None
        if file is not None and file["sha256"] not in found:
            found.append(file["sha256"])
    return found
