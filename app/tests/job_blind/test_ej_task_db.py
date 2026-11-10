"""The `errand` task exists: in the Task type, in the shipped routes, and in the spend ledger's check."""

import asyncio
from typing import get_args

import psycopg
import pytest
from ashley.db.pool import PoolDatabase
from ashley.inference import routes
from ashley.inference.model import Task, TaskName, Usage
from ashley.inference.postgres import PostgresSpendLedger
from ashley.inference.spend import Call
from contract.conversations_support import scalar


def test_errand_is_a_task() -> None:
    assert "errand" in get_args(Task)


def test_the_shipped_routes_list_errand() -> None:
    assert routes.load({}).for_task("errand")


def record(url: str, task: TaskName) -> None:
    async def go() -> None:
        db = PoolDatabase(url, connect_timeout_s=5.0)
        await db.open()
        try:
            await PostgresSpendLedger(db).record(Call(task, "p", "m", "ok", Usage(1, 1), None, 1))
        finally:
            await db.close()

    asyncio.run(go())


def test_the_spend_ledger_accepts_an_errand_call_after_migrating(db_url: str) -> None:
    record(db_url, "errand")
    assert scalar(db_url, "SELECT count(*) FROM inference_calls WHERE task = 'errand'") == 1


def test_the_spend_ledger_check_still_refuses_an_unknown_task(db_url: str) -> None:
    record(db_url, "errand")
    with psycopg.connect(db_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(b"UPDATE inference_calls SET task = 'zz_not_a_task'")
