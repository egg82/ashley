"""A fake Home Assistant for the automation tests, served through httpx2's MockTransport so `RestAutomations` runs its
real HTTP code with no network. It keeps configs by id and an entity per config (`automation.<id>`, on when written,
as HA's are), answers a write it is told to refuse with HA's 400 shape, and can go down from a given request on.
Shapes follow the live API read 2026-10-31: `/api/states` entities with `attributes.id`, `friendly_name` and
`last_triggered`; config bodies with their `id`; 404 for a missing id."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx2

from ashley.home_assistant.client import HomeAssistant
from ashley.home_assistant.rest_automations import AutomationsConfig, RestAutomations

CONFIG = AutomationsConfig(timeout_s=1, entity_tries=3, entity_wait_s=0)


@dataclass
class FakeHouse:
    configs: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    enabled: dict[str, bool] = field(default_factory=dict[str, bool])
    """By entity id."""
    yaml_only: list[str] = field(default_factory=list[str])
    """Entities with no config id (written in YAML)."""
    refuse: str | None = None
    """When set, every config write is refused with this message."""
    down_after: int | None = None
    """Requests answered before every later one fails to connect."""
    hidden_for: int = 0
    """How many state reads after a write leave the new entity out, as HA does while it reloads."""
    wake: bool = False
    """Whether `rest_command.ashley_wake` is set up in this HA's configuration."""
    services: Any = None
    """When set, what `/api/services` answers in place of the domains `wake` describes."""
    requests: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    writes: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """Every request that changed something: (method, path)."""

    def add(self, automation_id: str, alias: str, on: bool = True, **config: Any) -> str:
        self.configs[automation_id] = {"id": automation_id, "alias": alias, **config}
        entity = f"automation.{automation_id}"
        self.enabled[entity] = on
        return entity

    def entity_of(self, automation_id: str) -> str:
        return f"automation.{automation_id}"

    def client(self) -> RestAutomations:
        http = httpx2.AsyncClient(base_url="http://ha.test:8123", transport=httpx2.MockTransport(self.handle))
        return RestAutomations(HomeAssistant(http), CONFIG, sleep=_no_sleep)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if self.down_after is not None and len(self.requests) >= self.down_after:
            raise httpx2.ConnectError("down", request=request)
        method, path = request.method, request.url.path
        self.requests.append((method, path))
        if method != "GET":
            self.writes.append((method, path))
        if path == "/api/states":
            return httpx2.Response(200, json=self._states())
        if path == "/api/services" and self.services is not None:
            return httpx2.Response(200, json=self.services)
        if path == "/api/services":
            rest: dict[str, dict[str, Any]] = {"ashley_wake": {}} if self.wake else {"other": {}}
            return httpx2.Response(200, json=[{"domain": "automation", "services": {"turn_on": {}}},
                                              {"domain": "rest_command", "services": rest}])
        if path.startswith("/api/config/automation/config/"):
            return self._config(method, path.rsplit("/", 1)[1], request)
        if path in ("/api/services/automation/turn_on", "/api/services/automation/turn_off"):
            entity = json.loads(request.content)["entity_id"]
            if entity in self.enabled:
                self.enabled[entity] = path.endswith("turn_on")
            return httpx2.Response(200, json=[])
        return httpx2.Response(404, json={"message": "not found"})

    def _states(self) -> list[Mapping[str, Any]]:
        hiding = self.hidden_for > 0
        self.hidden_for = max(0, self.hidden_for - 1)
        out: list[Mapping[str, Any]] = [{"entity_id": "light.porch", "state": "off", "attributes": {}}]
        for automation_id, config in self.configs.items():
            entity = self.entity_of(automation_id)
            if hiding and automation_id.startswith("ashley_"):
                continue
            out.append({"entity_id": entity, "state": "on" if self.enabled.get(entity, True) else "off",
                        "attributes": {"id": automation_id, "friendly_name": config.get("alias", entity),
                                       "last_triggered": "2026-10-13T04:30:43.481239+00:00", "mode": "single"}})
        for entity in self.yaml_only:
            out.append({"entity_id": entity, "state": "on", "attributes": {"friendly_name": entity,
                                                                         "last_triggered": None}})
        return out

    def _config(self, method: str, automation_id: str, request: httpx2.Request) -> httpx2.Response:
        if method == "GET":
            found = self.configs.get(automation_id)
            return httpx2.Response(404, json={"message": "Resource not found"}) if found is None else \
                httpx2.Response(200, json=found)
        if method == "DELETE":
            if self.configs.pop(automation_id, None) is None:
                return httpx2.Response(404, json={"message": "Resource not found"})
            self.enabled.pop(self.entity_of(automation_id), None)
            return httpx2.Response(200, json={"result": "ok"})
        if self.refuse is not None:
            return httpx2.Response(400, json={"message": self.refuse})
        entity = self.entity_of(automation_id)
        fresh = automation_id not in self.configs
        self.configs[automation_id] = {"id": automation_id, **json.loads(request.content)}
        if fresh:
            self.enabled[entity] = True
        return httpx2.Response(200, json={"result": "ok"})


async def _no_sleep(_: float) -> None:
    return None
