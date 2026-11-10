"""Every task the code can name is listed by the shipped routes and accepted by the spend ledger's check, so a new
`Task` cannot ship without its routes and its migration."""

import asyncio

import psycopg
from ashley.db.migrate import migrate
from ashley.db.pool import PoolDatabase
from ashley.inference import routes
from ashley.inference.model import TaskName, Usage
from ashley.inference.postgres import PostgresSpendLedger
from ashley.inference.spend import Call

ALL: tuple[TaskName, ...] = (*routes.TASKS, *routes.SPEECH_TASKS, *routes.EMBED_TASKS, *routes.IMAGE_TASKS)


def test_the_shipped_routes_list_every_task() -> None:
    loaded = routes.load({})
    assert {"memory_write", "memory_judge"} <= set(loaded.by_task)
    assert all(loaded.for_task(task) for task in ALL)


def test_the_spend_ledger_accepts_every_task(empty_database: str) -> None:
    migrate(empty_database)

    async def scenario() -> None:
        db = PoolDatabase(empty_database, connect_timeout_s=5.0)
        await db.open()
        try:
            for task in ALL:
                await PostgresSpendLedger(db).record(Call(task, "p", "m", "ok", Usage(1, 1), None, 1))
        finally:
            await db.close()

    asyncio.run(scenario())
    with psycopg.connect(empty_database, autocommit=True) as conn:
        rows = conn.execute(b"SELECT task FROM inference_calls ORDER BY id").fetchall()
    assert [r[0] for r in rows] == list(ALL)
