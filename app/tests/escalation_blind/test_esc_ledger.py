"""The stronger route's calls are the spend ledger's task `escalated`, whose routes are `brainstorm`'s by reference."""

from decimal import Decimal

import psycopg
import pytest
from ashley.db.pool import PoolDatabase
from ashley.inference import routes
from ashley.inference.model import Usage
from ashley.inference.postgres import PostgresSpendLedger
from ashley.inference.reply import Reply
from ashley.inference.spend import Call
from contract.conversations_support import run, scalar
from contract.inference_support import FakeLedger, FakeProvider, ok, prompt, router, settle

SHIPPED = routes.load({})


def test_the_escalated_task_has_the_routes_brainstorm_has() -> None:
    assert SHIPPED.for_task("escalated") and SHIPPED.for_task("escalated") == SHIPPED.for_task("brainstorm")
    assert SHIPPED.for_task("escalated") != SHIPPED.for_task("chat")


def test_a_call_on_the_escalated_task_is_recorded_under_it_on_brainstorms_first_route() -> None:
    names = {r.provider for task in SHIPPED.by_task for r in SHIPPED.for_task(task)}
    providers = {name: FakeProvider(name, [ok("fine")]) for name in names}
    ledger = FakeLedger()
    inference = router(SHIPPED, list(providers.values()), ledger)
    settle(inference.generate("escalated", prompt("hello"), Reply))
    first = SHIPPED.for_task("brainstorm")[0]
    assert [(c.task, c.provider, c.model, c.outcome) for c in ledger.rows] == [
        ("escalated", first.provider, first.model, "ok")]
    assert [len(p.asked) for p in providers.values() if p.name == first.provider] == [1]


def test_the_spend_ledger_stores_a_row_for_the_escalated_task_and_still_refuses_an_unknown_one(db_url: str) -> None:
    async def go() -> None:
        db = PoolDatabase(db_url, connect_timeout_s=5.0)
        await db.open()
        try:
            await PostgresSpendLedger(db).record(
                Call("escalated", "anthropic", "m", "ok", Usage(10, 5), Decimal("0.001"), 250))
        finally:
            await db.close()

    run(go())
    assert scalar(db_url, "SELECT count(*) FROM inference_calls WHERE task = 'escalated'") == 1
    with psycopg.connect(db_url, autocommit=True) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(b"INSERT INTO inference_calls (task, provider, model, outcome, duration_ms) "
                     b"VALUES ('not_a_task', 'p', 'm', 'ok', 1)")


def test_the_ledger_reads_every_task_a_turn_can_use_in_one_database(db_url: str) -> None:
    for task in ("command", "chat", "brainstorm", "escalated"):
        scalar(db_url, "INSERT INTO inference_calls (task, provider, model, outcome, duration_ms) "
                       "VALUES (%s, 'p', 'm', 'ok', 1) RETURNING id", (task,))
    assert scalar(db_url, "SELECT count(DISTINCT task) FROM inference_calls") == 4
