"""Pinning a provider for the memory eval's tasks, its argument errors, and the report of who answered."""

import asyncio
from decimal import Decimal

import pytest
from ashley.db.migrate import migrate
from ashley.db.pool import PoolDatabase
from ashley.evals import memory_write
from ashley.evals.__main__ import main, pinned
from ashley.inference import routes
from ashley.inference.model import TaskName, Usage
from ashley.inference.postgres import PostgresSpendLedger, Spent, SpentBy, last_call_id, spent_by_after
from ashley.inference.spend import Call, Outcome
from ashley.memory.eval import write
from ashley.wiring import app_routes

SHIPPED = routes.load({})


def providers_of(loaded: routes.Routes, task: routes.Task) -> list[str]:
    return [r.provider for r in loaded.by_task[task]]


def test_only_keeps_the_named_providers_routes_in_order() -> None:
    narrowed = routes.only(SHIPPED, "memory_write", "gemini")
    assert narrowed.by_task["memory_write"] == tuple(r for r in SHIPPED.by_task["memory_write"] if r.provider == "gemini")
    assert providers_of(narrowed, "memory_write") == ["gemini"]


def test_only_leaves_every_other_task_and_the_cooldown_alone() -> None:
    narrowed = routes.only(SHIPPED, "memory_write", "gemini")
    for task in routes.TASKS:
        if task != "memory_write":
            assert narrowed.by_task[task] == SHIPPED.by_task[task]
    assert narrowed.cooldown_s == SHIPPED.cooldown_s and narrowed.speech == SHIPPED.speech


@pytest.mark.parametrize("provider", ["nope", "wyoming"])
def test_only_refuses_a_provider_the_task_has_no_route_for_naming_those_it_has(provider: str) -> None:
    with pytest.raises(routes.PinError) as caught:
        routes.only(SHIPPED, "memory_judge", provider)
    assert "anthropic" in str(caught.value) and "gemini" in str(caught.value)


def test_pinned_narrows_the_writer_and_the_judge_independently() -> None:
    both = pinned(SHIPPED, "gemini", "anthropic")
    assert providers_of(both, "memory_write") == ["gemini"] and providers_of(both, "memory_judge") == ["anthropic"]
    assert pinned(SHIPPED, None, None) == SHIPPED
    assert providers_of(pinned(SHIPPED, None, "gemini"), "memory_write") == providers_of(SHIPPED, "memory_write")


def test_the_app_writes_memory_on_the_first_route_only_and_leaves_the_rest() -> None:
    app = app_routes(SHIPPED)
    assert app.by_task["memory_write"] == SHIPPED.by_task["memory_write"][:1]
    assert providers_of(app, "memory_write") == ["anthropic"], "the write job waits for Sonnet, never the fallback"
    assert len(SHIPPED.by_task["memory_write"]) > 1, "the fallback stays shipped for the eval to pin"
    assert all(app.by_task[t] == SHIPPED.by_task[t] for t in routes.TASKS if t != "memory_write")


@pytest.mark.parametrize("flags",[["--writer", "nope"], ["--judge", "nope"], ["--writer", "anthropic", "--judge", "nope"]])
def test_an_unknown_pin_is_a_usage_error(flags: list[str], monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    assert main(["memory-write", *flags]) == 2
    err = capsys.readouterr().err
    assert "nope" in err and "anthropic" in err


def test_zero_runs_is_a_usage_error() -> None:
    assert main(["memory-write", "--runs", "0"]) == 2


def call(task: TaskName, provider: str, model: str, outcome: Outcome, cost: str | None) -> Call:
    return Call(task, provider, model, outcome, Usage(1, 1), None if cost is None else Decimal(cost), 1)


def test_a_run_answered_by_two_providers_reports_two_lines_and_says_mixed(empty_database: str) -> None:
    migrate(empty_database)

    async def scenario() -> list[SpentBy]:
        db = PoolDatabase(empty_database, connect_timeout_s=5.0)
        await db.open()
        try:
            ledger = PostgresSpendLedger(db)
            await ledger.record(call("memory_write", "anthropic", "claude-haiku-5-5", "ok", "0.01"))
            mark = await last_call_id(db)
            await ledger.record(call("chat", "anthropic", "claude-sonnet-5-5", "ok", "1"))
            for c in (call("memory_write", "anthropic", "claude-haiku-5-5", "unavailable", "0"),
                      call("memory_write", "gemini", "gemini-3.5-flash-lite", "ok", "0.002"),
                      call("memory_write", "gemini", "gemini-3.5-flash-lite", "ok", None),
                      call("memory_judge", "gemini", "gemini-3.5-flash-lite", "ok", "0.001")):
                await ledger.record(c)
            return await spent_by_after(db, mark, memory_write.TASKS)
        finally:
            await db.close()

    by = asyncio.run(scenario())
    assert [(b.task, b.provider, b.outcome) for b in by] == [
        ("memory_judge", "gemini", "ok"), ("memory_write", "anthropic", "unavailable"), ("memory_write", "gemini", "ok")]
    assert by[2].spent == Spent(2, Decimal("0.002"), 1)
    text = memory_write.render(memory_write.Outcome(write.WriteReport(()), Spent(4, Decimal(0), 1), by))
    answered = [line for line in text.splitlines() if line.startswith("answered: memory_write")]
    assert len(answered) == 2 and "plus 1 with no price" in answered[1]
    assert [line for line in text.splitlines() if line.startswith("MIXED")] == [
        "MIXED: memory_write was answered by anthropic, gemini; the pass rate is not one model's"]
