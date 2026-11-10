"""The house eval's second guard, under the per-turn tools: `ReadOnlyHomes` hands every household a Home whose House reads
from the real one and keeps every change from it. A change (an action, a config, a record) is noted in `refused` as an
`Attempt` named `house:<what>` and answered as made, so `house_change` cannot reach a house the eval is pointed at, whatever
the case expects; `house_do` and the other everyday tools are `GuardedTools`' to keep."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..home_assistant.homes import Home, Homes
from ..home_assistant.house import (ActionInfo, ConfigItem, ConfigKind, House, LogEntry, Performed, Record, RecordKind,
                                    Series, State, Window)
from .house_guard import Attempt


class ReadOnlyHouse(House):
    def __init__(self, inner: House, refused: list[Attempt]) -> None:
        self._inner = inner
        self._refused = refused

    def _kept(self, what: str) -> None:
        self._refused.append(Attempt(f"house:{what}", ""))

    def offered(self) -> bool:
        return self._inner.offered()

    async def states(self) -> tuple[State, ...]:
        return await self._inner.states()

    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        return await self._inner.records(kind)

    async def history(self, window: Window) -> tuple[Series, ...]:
        return await self._inner.history(window)

    async def logbook(self, window: Window) -> tuple[LogEntry, ...]:
        return await self._inner.logbook(window)

    async def actions(self) -> tuple[ActionInfo, ...]:
        return await self._inner.actions()

    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        return await self._inner.configs(kind)

    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        return await self._inner.config(kind, config_id)

    async def diagnostics(self, integration_id: str) -> Mapping[str, Any] | None:
        return await self._inner.diagnostics(integration_id)

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        self._kept(f"perform:{action}")
        return Performed()

    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        self._kept(f"write:{kind}")
        return config_id or "new"

    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        self._kept(f"delete:{kind}")
        return True

    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        self._kept(f"create:{kind}")
        return "new"

    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        self._kept(f"update:{kind}")

    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        self._kept(f"delete:{kind}")


class ReadOnlyHomes(Homes):
    def __init__(self, inner: Homes, refused: list[Attempt]) -> None:
        self._inner = inner
        self._refused = refused

    async def of(self, household_id: int) -> Home | None:
        home = await self._inner.of(household_id)
        return None if home is None else replace(home, house=ReadOnlyHouse(home.house, self._refused))

    async def check(self, base_url: str, token: str) -> None:
        await self._inner.check(base_url, token)
