"""The scratch household a bench replay runs in, and the turns said on the bench's thread before the replayed
conversation, stored as they were with every time moved by the same offset, so the ages she reads stay as they were."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

from .. import services
from ..db.database import Database
from ..people import admin
from .bench_replay_snapshot import Said


def seat(database_url: str, zone: str, person: str) -> tuple[int, int]:
    """A new household in `zone` with one person named `person`: their ids."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        household = admin.add_household(conn, "bench-replay", zone)
        return household, admin.add_person(conn, household, person)


async def turns(household_id: int, person_id: int, bench_id: int, said: Sequence[Said], offset: float) -> int:
    """Store `said` (whole conversations, oldest first) on the bench's thread, each conversation remembered with the
    person taking part; how many turns were stored."""
    made: dict[int, int] = {}
    ids: dict[int, int] = {}
    async with services.get(Database).connection() as conn:
        for t in said:
            if t.conversation_id not in made:
                made[t.conversation_id] = await _conversation(conn, household_id, person_id, bench_id, t.at + offset)
            row = await (await conn.execute(
                "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, at, visibility, owner_id, "
                "follows, answers, source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (made[t.conversation_id], household_id, t.author, person_id if t.author == "person" else None, t.text,
                 _when(t.at + offset), t.visibility, person_id, t.follows,
                 ids.get(t.answers) if t.answers is not None else None, t.source))).fetchone()
            assert row is not None
            ids[t.id] = int(row[0])
            await conn.execute("UPDATE conversations SET last_activity_at = %s WHERE id = %s",
                               (_when(t.at + offset), made[t.conversation_id]))
    return len(ids)


async def _conversation(conn: psycopg.AsyncConnection[tuple[Any, ...]], household_id: int, person_id: int, bench_id: int,
                        at: float) -> int:
    row = await (await conn.execute(
        "INSERT INTO conversations (household_id, kind, started_at, last_activity_at, remembered, channel, thread) "
        "VALUES (%s, 'brainstorm', %s, %s, true, 'web', %s) RETURNING id",
        (household_id, _when(at), _when(at), f"bench:{bench_id}"))).fetchone()
    assert row is not None
    await conn.execute("INSERT INTO conversation_participants (conversation_id, household_id, person_id) "
                       "VALUES (%s, %s, %s)", (row[0], household_id, person_id))
    return int(row[0])


def _when(at: float) -> datetime:
    return datetime.fromtimestamp(at, UTC)
