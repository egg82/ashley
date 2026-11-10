"""The provider watch (`ashley.inference.watch`): which provider's failed share of recent chat calls raises an alert, read
from the real spend ledger, and the tunables that decide it."""

import asyncio
import logging
from collections.abc import Generator

import psycopg
import pytest
from ashley import services
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.inference import watch
from ashley.inference.outcomes import Share
from contract.conversations_support import db_url as db_url, migrated_template as migrated_template

CONFIG = watch.WatchConfig(60, 600, 5, 0.5, ("error", "unavailable", "invalid_output"), ("chat",))


def test_the_shipped_tunables_load() -> None:
    loaded = watch.load()
    assert loaded.tasks and loaded.failing and loaded.min_calls >= 1 and 0 < loaded.error_share <= 1


@pytest.mark.parametrize("bad", [
    {}, {"interval_s": 1, "window_s": 1, "min_calls": 0, "error_share": 0.5, "failing": ["error"], "tasks": ["chat"]},
    {"interval_s": 1, "window_s": 1, "min_calls": 1, "error_share": 0, "failing": ["error"], "tasks": ["chat"]},
    {"interval_s": 1, "window_s": 1, "min_calls": 1, "error_share": 0.5, "failing": ["ok"], "tasks": ["chat"]},
    {"interval_s": 1, "window_s": 1, "min_calls": 1, "error_share": 0.5, "failing": ["error"], "tasks": ["nope"]}])
def test_tunables_that_cannot_work_are_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        watch.parse(bad)


def test_a_provider_alerts_only_with_enough_calls_and_a_high_enough_failed_share() -> None:
    seen = [Share("chat", "a", 10, 5), Share("chat", "b", 10, 4), Share("chat", "c", 4, 4), Share("chat", "d", 5, 5)]
    assert [s.provider for s in watch.breaches(seen, CONFIG)] == ["a", "d"]


@pytest.fixture
def ledger(db_url: str) -> Generator[str]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        for provider, outcome, count, age in (("gemini", "error", 8, 60), ("gemini", "ok", 2, 60),
                                              ("anthropic", "ok", 9, 60), ("anthropic", "error", 1, 60),
                                              ("openai", "error", 3, 60), ("anthropic", "error", 20, 7200)):
            for _ in range(count):
                conn.execute(b"INSERT INTO inference_calls (task, provider, model, outcome, duration_ms, at) "
                             b"VALUES ('chat', %s, 'm', %s, 1, now() - make_interval(secs => %s))",
                             (provider, outcome, age))
        conn.execute(b"INSERT INTO inference_calls (task, provider, model, outcome, duration_ms) "
                     b"SELECT 'brainstorm', 'gemini', 'm', 'error', 1 FROM generate_series(1, 9)")
    yield db_url


def test_the_evaluation_reads_the_ledger_alerting_on_the_provider_failing_in_the_window_for_a_watched_task(
        ledger: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, "ashley.inference")

    async def scenario() -> list[Share]:
        db = PoolDatabase(ledger, connect_timeout_s=5.0)
        await db.open()
        services.register(Database, db)
        try:
            return await watch.evaluate(CONFIG)
        finally:
            services.unregister(Database)
            await db.close()

    alerts = asyncio.run(scenario())
    assert [(s.provider, s.calls, s.failed) for s in alerts] == [("gemini", 10, 8)]
    fields = {r.getMessage(): getattr(r, "fields") for r in caplog.records}
    assert fields["inference.provider_alert"] == {"task": "chat", "provider": "gemini", "calls": 10, "failed": 8,
                                                  "share": 0.8, "window_s": 600}
    assert fields["inference.watch"]["pairs"] == 3 and fields["inference.watch"]["alerts"] == 1
