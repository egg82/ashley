"""Detections in Postgres: table `camera_detections`, keyed by household, camera and the time the detector saw the event."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg

from .. import services
from ..db.database import Database, DatabaseUnavailable
from ..text import has_nul
from .detections import Claim, Detections, DetectionsUnavailable
from .model import Detection


@contextmanager
def _translated() -> Generator[None]:
    try:
        yield
    except DatabaseUnavailable as e:
        raise DetectionsUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise DetectionsUnavailable("database unreachable") from e


class PostgresDetections(Detections):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def claim(self, household_id: int, detection: Detection, min_gap_s: float) -> Claim:
        if has_nul(detection.camera_id) or has_nul(detection.kind):
            raise ValueError("a detection's camera and class may not hold a NUL")
        gap = timedelta(seconds=min_gap_s)
        with _translated():
            async with self._database.connection() as conn:
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                                   (f"camera_detections/{household_id}/{detection.camera_id}",))
                cur = await conn.execute(
                    "INSERT INTO camera_detections (household_id, camera_id, at, kind) VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING", (household_id, detection.camera_id, detection.at, detection.kind))
                if cur.rowcount == 0:
                    return "duplicate"
                cur = await conn.execute(
                    "SELECT 1 FROM camera_detections WHERE household_id = %s AND camera_id = %s AND shown "
                    "AND at BETWEEN %s AND %s", (household_id, detection.camera_id, detection.at - gap, detection.at + gap))
                return "too_soon" if await cur.fetchone() is not None else "new"

    async def shown(self, household_id: int, detection: Detection) -> None:
        with _translated():
            async with self._database.connection() as conn:
                await conn.execute("UPDATE camera_detections SET shown = true WHERE household_id = %s "
                                   "AND camera_id = %s AND at = %s", (household_id, detection.camera_id, detection.at))

    async def prune(self, now: datetime, keep_s: float) -> int:
        with _translated():
            async with self._database.connection() as conn:
                cur = await conn.execute("DELETE FROM camera_detections WHERE at < %s", (now - timedelta(seconds=keep_s),))
                return cur.rowcount


def register(database: Database) -> None:
    """Make `PostgresDetections` over `database` the answer to `services.get(Detections)`."""
    services.register(Detections, PostgresDetections(database))
