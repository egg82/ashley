"""The house's automations through Home Assistant's REST API: `/api/states` for the list (every `automation.*` entity,
its config id in `attributes.id`), `/api/config/automation/config/<id>` to read, write (POST creates or replaces, and
HA reloads it) and delete one, and the `automation.turn_on` / `turn_off` services. The token needs an HA admin user.

Tunables are data, `automations.json` beside this module: `timeout_s` for each request, and how long a written
automation is waited for as an entity (`entity_tries` reads `entity_wait_s` apart), since HA reloads it after
answering the write."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx2

from .automations import Automation, AutomationRejected, Automations, AutomationsUnavailable
from .client import HomeAssistant

FILE = Path(__file__).with_name("automations.json")
_CONFIG = "/api/config/automation/config/"


@dataclass(frozen=True)
class AutomationsConfig:
    timeout_s: float
    entity_tries: int
    entity_wait_s: float


def load() -> AutomationsConfig:
    raw = json.loads(FILE.read_text())
    if set(raw) != {"timeout_s", "entity_tries", "entity_wait_s"}:
        raise ValueError("automations.json has exactly timeout_s, entity_tries and entity_wait_s")
    config = AutomationsConfig(float(raw["timeout_s"]), int(raw["entity_tries"]), float(raw["entity_wait_s"]))
    if config.timeout_s <= 0 or config.entity_tries < 1 or config.entity_wait_s < 0:
        raise ValueError("automations.json: timeout_s above 0, entity_tries at least 1, entity_wait_s 0 or more")
    return config


class RestAutomations(Automations):
    def __init__(self, home_assistant: HomeAssistant, config: AutomationsConfig,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self._http = home_assistant.http
        self._config = config
        self._sleep = sleep

    def offered(self) -> bool:
        return True

    async def listed(self) -> list[Automation]:
        got = await self._send("GET", "/api/states", "list")
        raw: object = _json(got, "list")
        loose: Any = raw
        if not isinstance(raw, list):
            raise AutomationsUnavailable("list: not a list of states")
        found = [_automation(s) for s in (_object(item) for item in list[object](loose)) if s is not None]
        return sorted((a for a in found if a is not None), key=lambda a: a.entity_id)

    async def has_service(self, name: str) -> bool | None:
        parts = name.split(".")
        if len(parts) != 2 or not all(parts):
            return None
        domain, service = parts
        try:
            raw: object = _json(await self._send("GET", "/api/services", "services"), "services")
        except AutomationsUnavailable:
            return None
        loose: Any = raw
        if not isinstance(raw, list):
            return None
        offered: dict[str, dict[str, Any]] = {}
        for item in (_object(i) for i in list[object](loose)):
            listed = None if item is None else _object(item.get("services"))
            if item is None or not isinstance(item.get("domain"), str) or listed is None:
                return None
            offered[item["domain"]] = listed
        return service in offered[domain] if domain in offered else False

    async def config(self, automation_id: str) -> dict[str, Any] | None:
        got = await self._send("GET", _CONFIG + quote(automation_id, safe=""), "read")
        if got.status_code == 404:
            return None
        raw = _object(_json(got, "read"))
        if raw is None:
            raise AutomationsUnavailable("read: not an object")
        return raw

    async def write(self, automation_id: str, config: Mapping[str, Any]) -> str | None:
        got = await self._send("POST", _CONFIG + quote(automation_id, safe=""), "write", dict(config))
        if got.status_code == 400:
            raise AutomationRejected(_message(got))
        _json(got, "write")
        for attempt in range(self._config.entity_tries):
            if attempt:
                await self._sleep(self._config.entity_wait_s)
            entity = next((a.entity_id for a in await self.listed() if a.automation_id == automation_id), None)
            if entity is not None:
                return entity
        return None

    async def delete(self, automation_id: str) -> bool:
        got = await self._send("DELETE", _CONFIG + quote(automation_id, safe=""), "delete")
        if got.status_code in (400, 404):
            return False
        _json(got, "delete")
        return True

    async def set_enabled(self, entity_id: str, enabled: bool) -> None:
        service = "turn_on" if enabled else "turn_off"
        got = await self._send("POST", f"/api/services/automation/{service}", service, {"entity_id": entity_id})
        _json(got, service)

    async def _send(self, method: str, path: str, step: str, body: object = None) -> httpx2.Response:
        try:
            return await self._http.request(method, path, json=body, timeout=self._config.timeout_s)
        except httpx2.HTTPError as e:
            raise AutomationsUnavailable(f"{step}: {type(e).__name__}") from e


def _json(got: httpx2.Response, step: str) -> Any:
    if got.status_code // 100 != 2:
        raise AutomationsUnavailable(f"{step}: status {got.status_code}")
    try:
        return got.json()
    except ValueError as e:
        raise AutomationsUnavailable(f"{step}: not JSON") from e


def _message(got: httpx2.Response) -> str:
    try:
        raw = _object(got.json())
    except ValueError:
        return "Home Assistant refused the config"
    message = None if raw is None else raw.get("message")
    return message if isinstance(message, str) and message else "Home Assistant refused the config"


def _automation(state: Mapping[str, Any]) -> Automation | None:
    entity = state.get("entity_id")
    if not isinstance(entity, str) or not entity.startswith("automation."):
        return None
    attributes = _object(state.get("attributes")) or {}
    automation_id = attributes.get("id")
    alias = attributes.get("friendly_name")
    return Automation(automation_id if isinstance(automation_id, str) else None, entity,
                      alias if isinstance(alias, str) else entity, state.get("state") == "on",
                      _moment(attributes.get("last_triggered")))


def _object(data: object) -> dict[str, Any] | None:
    loose: Any = data
    return {str(k): v for k, v in dict[object, object](loose).items()} if isinstance(data, dict) else None


def _moment(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
