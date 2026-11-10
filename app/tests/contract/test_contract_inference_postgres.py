"""`PostgresSpendLedger` against a real database (migration 0003): rows as documented, NULLs, exact numeric, the
database's clock, and the table's CHECKs refusing bad rows."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from ashley.inference.routes import TASKS
from ashley.inference.model import Task
from ashley.db.pool import PoolDatabase
from ashley.inference.model import Usage
from ashley.inference.postgres import PostgresSpendLedger
from ashley.inference.spend import Call, Outcome
from contract_support import unreachable_conninfo
from conversations_support import db_now, run, scalar
from inference_support import ANY_TASK

OUTCOMES: tuple[Outcome, ...] = ("ok", "refused", "unavailable", "invalid_output", "error")
COLUMNS = ("task, provider, model, outcome, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
           "cost_usd, duration_ms")
SLACK = timedelta(seconds=5)


@asynccontextmanager
async def ledger(url: str) -> AsyncGenerator[PostgresSpendLedger]:
    db = PoolDatabase(url, connect_timeout_s=5.0)
    await db.open()
    try:
        yield PostgresSpendLedger(db)
    finally:
        await db.close()


@contextmanager
def refused() -> Generator[None]:
    """The block must raise, and not merely because the code is not written."""
    with pytest.raises(Exception) as caught:
        yield
    assert not isinstance(caught.value, NotImplementedError)


def stored(url: str, order: str = "id") -> list[tuple[Any, ...]]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(f"SELECT {COLUMNS} FROM inference_calls ORDER BY {order}".encode()).fetchall()


def record(url: str, *calls: Call) -> None:
    async def scenario() -> None:
        async with ledger(url) as spend:
            for call in calls:
                await spend.record(call)

    run(scenario())


def call(task: Task = "chat", outcome: Outcome = "ok", usage: Usage | None = Usage(11, 22, 33, 44),
         cost: Decimal | None = Decimal("0.5"), duration_ms: int = 123, provider: str = "alpha",
         model: str = "m1") -> Call:
    return Call(task, provider, model, outcome, usage, cost, duration_ms)


def ids_of(url: str) -> list[int]:
    with psycopg.connect(url, autocommit=True) as conn:
        return [int(r[0]) for r in conn.execute(b"SELECT id FROM inference_calls ORDER BY id").fetchall()]


def test_a_call_is_stored_as_one_row_with_every_column_as_documented(db_url: str) -> None:
    record(db_url, call("brainstorm", "refused", Usage(11, 22, 33, 44), Decimal("0.5"), 987, "gemini", "g-pro"))
    assert stored(db_url) == [("brainstorm", "gemini", "g-pro", "refused", 11, 22, 33, 44, Decimal("0.5"), 987)]


def test_every_kind_and_every_outcome_is_accepted_and_comes_back(db_url: str) -> None:
    sent = [call(k, o) for k in TASKS for o in OUTCOMES]
    record(db_url, *sent)
    assert [(r[0], r[3]) for r in stored(db_url)] == [(c.task, c.outcome) for c in sent]


def test_rows_get_increasing_distinct_ids_in_the_order_recorded(db_url: str) -> None:
    record(db_url, *[call(duration_ms=n) for n in (5, 4, 3, 2, 1)])
    ids = [int(scalar(db_url, "SELECT id FROM inference_calls WHERE duration_ms = %s", (n,))) for n in (5, 4, 3, 2, 1)]
    assert ids == sorted(set(ids))


def test_unknown_usage_stores_all_four_token_columns_null_together(db_url: str) -> None:
    record(db_url, call(usage=None, cost=None, outcome="unavailable"))
    assert stored(db_url) == [("chat", "alpha", "m1", "unavailable", None, None, None, None, None, 123)]


def test_a_cost_of_none_is_null_and_a_cost_of_zero_is_zero(db_url: str) -> None:
    record(db_url, call(cost=None), call(cost=Decimal(0)), call(usage=Usage(0, 0, 0, 0), cost=Decimal(0)))
    rows = stored(db_url)
    assert [r[8] for r in rows] == [None, Decimal(0), Decimal(0)]
    assert [r[8] is None for r in rows] == [True, False, False]
    assert rows[2][4:8] == (0, 0, 0, 0), "zero tokens are zero, not unknown"


@pytest.mark.parametrize("cost", [
    Decimal("0.1234567890123456789012"), Decimal("0.000000000001"), Decimal("12345678901234567890.5"),
    Decimal("0.010935"), Decimal("3.1"),
])
def test_cost_is_stored_exactly_not_as_a_float(db_url: str, cost: Decimal) -> None:
    record(db_url, call(cost=cost))
    got = stored(db_url)[0][8]
    assert got == cost
    assert scalar(db_url, "SELECT cost_usd::text FROM inference_calls").rstrip("0") == format(cost, "f").rstrip("0")


def test_the_stamp_is_a_timestamptz_from_the_databases_clock_at_the_time_of_the_call(db_url: str) -> None:
    before = db_now(db_url)
    record(db_url, call(), call())
    after = db_now(db_url)
    stamps = [scalar(db_url, "SELECT at FROM inference_calls WHERE id = %s", (i,)) for i in ids_of(db_url)]
    assert len(stamps) == 2 and all(s.tzinfo is not None for s in stamps)
    assert before - SLACK <= stamps[0] <= stamps[1] <= after + SLACK
    assert stamps[0].astimezone(UTC).utcoffset() == timedelta(0)


def test_the_table_has_the_documented_column_types(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        rows = conn.execute(b"SELECT column_name, data_type, numeric_precision FROM information_schema.columns "
                            b"WHERE table_name = 'inference_calls'").fetchall()
    types = {r[0]: (r[1], r[2]) for r in rows}
    assert {n: t[0] for n, t in types.items()} == {
        "id": types["id"][0], "at": "timestamp with time zone", "task": "text", "provider": "text", "model": "text",
        "outcome": "text", "input_tokens": "integer", "output_tokens": "integer", "cache_read_tokens": "integer",
        "cache_write_tokens": "integer", "audio_ms": "integer", "characters": "integer", "cost_usd": "numeric",
        "duration_ms": "integer", "conversation_id": "bigint"}
    assert types["cost_usd"][1] is None, "numeric with no precision, so nothing is rounded"


# --- the CHECKs, tried on raw rows -------------------------------------------------------------------------------

GOOD: dict[str, Any] = {"task": "chat", "provider": "p", "model": "m", "outcome": "ok", "input_tokens": 1,
                        "output_tokens": 2, "cache_read_tokens": 3, "cache_write_tokens": 4, "cost_usd": Decimal("1"),
                        "duration_ms": 5}
BAD: dict[str, dict[str, Any]] = {
    "unknown task": {"task": "shout"},
    "unknown outcome": {"outcome": "great"},
    "outcome in the wrong case": {"outcome": "OK"},
    "negative input tokens": {"input_tokens": -1},
    "negative output tokens": {"output_tokens": -1},
    "negative cache read": {"cache_read_tokens": -1},
    "negative cache write": {"cache_write_tokens": -1},
    "only input null": {"input_tokens": None},
    "only output null": {"output_tokens": None},
    "only cache read null": {"cache_read_tokens": None},
    "only cache write null": {"cache_write_tokens": None},
    "two tokens null": {"input_tokens": None, "output_tokens": None},
    "three tokens null": {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None},
    "negative cost": {"cost_usd": Decimal("-0.000001")},
    "negative duration": {"duration_ms": -1},
}


def insert(url: str, **changes: Any) -> None:
    row = {**GOOD, **changes}
    columns = ", ".join(row)
    marks = ", ".join(["%s"] * len(row))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"INSERT INTO inference_calls (at, {columns}) VALUES (now(), {marks})".encode(),
                     tuple(row.values()))


def count(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM inference_calls"))


def test_the_controls_for_the_check_tests_insert_fine(db_url: str) -> None:
    insert(db_url)
    insert(db_url, input_tokens=None, output_tokens=None, cache_read_tokens=None, cache_write_tokens=None)
    insert(db_url, cost_usd=None)
    insert(db_url, cost_usd=0, duration_ms=0, input_tokens=0, output_tokens=0, cache_read_tokens=0,
           cache_write_tokens=0)
    assert count(db_url) == 4


@pytest.mark.parametrize("changes", BAD.values(), ids=BAD.keys())
def test_the_table_refuses_a_bad_row(db_url: str, changes: dict[str, Any]) -> None:
    insert(db_url)
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(db_url, **changes)
    assert count(db_url) == 1


def test_the_ledger_refuses_a_call_the_table_refuses_and_stores_nothing(db_url: str) -> None:
    async def scenario() -> None:
        async with ledger(db_url) as spend:
            with refused():
                await spend.record(call(duration_ms=-5))
            with refused():
                await spend.record(call(usage=Usage(-1, 0, 0, 0)))
            with refused():
                await spend.record(call(ANY_TASK))
            await spend.record(call())

    run(scenario())
    assert count(db_url) == 1


# --- failures and concurrency ---------------------------------------------------------------------------------


def test_record_raises_when_the_database_is_unreachable() -> None:
    async def scenario() -> None:
        db = PoolDatabase(unreachable_conninfo(), connect_timeout_s=0.5)
        await db.open()
        try:
            spend = PostgresSpendLedger(db)
            with refused():
                await spend.record(call())
        finally:
            await db.close()

    run(scenario())


def test_record_raises_rather_than_swallowing_when_the_table_is_gone(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(b"DROP TABLE inference_calls")

    async def scenario() -> None:
        async with ledger(db_url) as spend:
            with refused():
                await spend.record(call())

    run(scenario())


def test_many_concurrent_records_are_all_stored(db_url: str) -> None:
    async def scenario() -> None:
        async with ledger(db_url) as spend:
            await asyncio.gather(*[spend.record(call(duration_ms=n)) for n in range(25)])

    run(scenario())
    assert sorted(r[-1] for r in stored(db_url)) == list(range(25))
