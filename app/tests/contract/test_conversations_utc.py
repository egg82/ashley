"""Directed, not blind: every time the service returns is UTC (`model.py`), whatever timezone the database session
runs in."""

from datetime import timedelta

import psycopg
from ashley.conversations.model import NewTurn
from conversations_support import household, person, run, service
from psycopg import sql


def test_times_are_utc_when_the_database_runs_in_another_timezone(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()
        assert name is not None
        conn.execute(sql.SQL("ALTER DATABASE {} SET timezone = 'America/Denver'").format(sql.Identifier(name[0])))
    home = household(db_url)
    alana = person(db_url, home)

    async def scenario() -> None:
        async with service(db_url) as conversations:
            started = await conversations.start(home, "chat", [alana])
            turn = await conversations.add_turn(started.id, NewTurn("person", "hello", alana))
            seen = await conversations.get(started.id)
        assert seen is not None
        moments = [started.started_at, started.last_activity_at, turn.at, seen.started_at, seen.last_activity_at,
                   *(t.at for t in seen.turns)]
        assert all(m.utcoffset() == timedelta(0) for m in moments), [m.isoformat() for m in moments]

    run(scenario())
