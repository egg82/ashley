"""Shared pieces of the provider-watch blind contract tests: the real ledger on a throwaway database, rows written
through the ledger's public `record` and back-dated, watch configs built through `watch.parse`, scripted providers
behind the real router, and log capture by event."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, TypeVar

import pytest
from ashley import services
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.inference import watch
from ashley.inference.model import (Entry, Message, Prompt, Route, SystemPrompt, Task, ToolCall, ToolCalls, ToolChoice,
                                    ToolSpec, Usage)
from ashley.inference.prices import Period, Prices, Tier
from ashley.inference.provider import Completion, Failure, Provider, ProviderFailed, ProviderRefused, ToolUse
from ashley.inference.postgres import PostgresSpendLedger, last_call_id
from ashley.inference.router import RoutedInference
from ashley.inference.routes import TASKS, Routes
from ashley.inference.spend import Call, Outcome
from ashley.inference.watch import WatchConfig
from pydantic import BaseModel

T = TypeVar("T")
FAILURES: tuple[Failure, ...] = ("unavailable", "invalid_output", "error")
FAILURE_NAMED: dict[str, Failure] = {f: f for f in FAILURES}
ALERT = "inference.provider_alert"
PASS = "inference.watch"
UNAVAILABLE = "inference.watch_unavailable"
ALERT_FIELDS = {"task", "provider", "calls", "failed", "share", "window_s"}

CONFIG_DATA: dict[str, object] = {"interval_s": 60, "window_s": 600, "min_calls": 5, "error_share": 0.5,
                                  "failing": ["error", "unavailable", "invalid_output"], "tasks": ["chat"]}


def go(scenario: Coroutine[Any, Any, T], limit: float = 25.0) -> T:
    async def bounded() -> T:
        return await asyncio.wait_for(scenario, limit)

    return asyncio.run(bounded())


def config(**changes: object) -> WatchConfig:
    """A config through `watch.parse`: the documented defaults with `changes` applied."""
    return watch.parse({**CONFIG_DATA, **changes})


def without(key: str) -> dict[str, object]:
    return {k: v for k, v in CONFIG_DATA.items() if k != key}


def fields_of(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    return [dict(getattr(r, "fields", {})) for r in caplog.records if r.getMessage() == event]


def records_of(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == event]


@dataclass
class Rig:
    db: Database
    ledger: PostgresSpendLedger

    async def add(self, task: Task, provider: str, outcome: Outcome, count: int = 1, age_s: float = 0.0) -> None:
        """`count` ledger rows, recorded through `record` and then aged `age_s` seconds by the database's clock."""
        mark = await last_call_id(self.db)
        for _ in range(count):
            await self.ledger.record(Call(task, provider, "m1", outcome, None, None, 5, None))
        if age_s:
            async with self.db.connection() as conn:
                await conn.execute(b"UPDATE inference_calls SET at = now() - make_interval(secs => %s) WHERE id > %s",
                                   (age_s, mark))

    async def clear(self) -> None:
        async with self.db.connection() as conn:
            await conn.execute(b"DELETE FROM inference_calls")


@asynccontextmanager
async def rig(url: str) -> AsyncGenerator[Rig]:
    """The real Postgres ledger, with its database registered as the `Database` service."""
    db = PoolDatabase(url)
    await db.open()
    services.register(Database, db)
    try:
        yield Rig(db, PostgresSpendLedger(db))
    finally:
        services.unregister(Database)
        await db.close()


# --- a router over scripted providers ---------------------------------------------------------------------------

TIER = Tier(None, input=Decimal("3"), cache_write=Decimal("3.75"), cache_read=Decimal("0.3"), output=Decimal("15"))
OPEN = Period(None, None, (TIER,))
PRICES = Prices({"alpha": {"m1": (OPEN,)}, "beta": {"m1": (OPEN,)}})
USAGE = Usage(input_tokens=10, output_tokens=5, cache_read_tokens=0, cache_write_tokens=0)


class Scripted(Provider):
    """Plays one scripted result per call (the last repeats): a Failure name, 'refused', or 'ok'."""

    def __init__(self, name: str, script: Iterable[str]) -> None:
        self._name = name
        self._script = list(script)
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def check_params(self, params: Mapping[str, object]) -> None:
        return None

    async def complete[M: BaseModel](self, model: str, params: Mapping[str, object], system: SystemPrompt,
                                      messages: tuple[Entry, ...], tools: tuple[ToolSpec, ...],
                                      tool_choice: ToolChoice, output: type[M],
                                      timeout_s: float) -> Completion[M] | ToolUse:
        step = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if step in ("tools", "stray_tools"):
            asked = "lamp" if step == "tools" else "stranger"
            return ToolUse(ToolCalls((ToolCall("c1", asked, {}),)), USAGE)
        if step == "refused":
            raise ProviderRefused("declined", USAGE)
        if step in FAILURE_NAMED:
            raise ProviderFailed(FAILURE_NAMED[step], f"{step} (status 000)", USAGE)
        return Completion(output.model_validate({"spoken": "hi", "text": "hi"}), USAGE)


def routed(ledger: PostgresSpendLedger, order: Iterable[Provider], task: Task = "chat") -> RoutedInference:
    providers = list(order)
    routes = tuple(Route(p.name, "m1", 10.0, "default", {}) for p in providers)
    by_task: dict[Task, tuple[Route, ...]] = {k: routes for k in TASKS}
    return RoutedInference(Routes(by_task, 0.001), providers, ledger, PRICES, lambda: 0.0, lambda: date(2026, 11, 2))


def prompt(tools: tuple[ToolSpec, ...] = ()) -> Prompt:
    return Prompt({"default": SystemPrompt("be Ashley")}, (Message("person", "hello"),), tools=tools)


LAMP = ToolSpec("lamp", "turns the lamp on", {"type": "object"})
