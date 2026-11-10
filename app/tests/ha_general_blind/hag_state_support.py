"""The stand-in Home Assistant's state: what it holds and what it was asked (see `hag_server_support`)."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

TOKEN = "hag-long-lived-token-9f3a"
T0 = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
Json = dict[str, Any]


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


@dataclass
class Ha:
    """Everything the stand-in holds, and what it was asked."""

    url: str = ""
    token: str = TOKEN
    states: dict[str, Json] = field(default_factory=dict[str, Json])
    entities: dict[str, Json] = field(default_factory=dict[str, Json])
    devices: dict[str, Json] = field(default_factory=dict[str, Json])
    areas: dict[str, Json] = field(default_factory=dict[str, Json])
    floors: dict[str, Json] = field(default_factory=dict[str, Json])
    labels: dict[str, Json] = field(default_factory=dict[str, Json])
    entries: dict[str, Json] = field(default_factory=dict[str, Json])
    diagnostics: dict[str, Json] = field(default_factory=dict[str, Json])
    services: dict[str, dict[str, Json]] = field(default_factory=dict[str, dict[str, Json]])
    responses: dict[str, Json] = field(default_factory=dict[str, Json])
    effects: dict[str, Callable[[Ha, Json], list[str]]] = field(default_factory=dict[str, Callable[["Ha", Json], list[str]]])
    configs: dict[str, dict[str, Json]] = field(default_factory=lambda: {"automation": {}, "script": {}})
    helpers: dict[str, dict[str, Json]] = field(default_factory=dict[str, dict[str, Json]])
    history: dict[str, list[tuple[datetime, str]]] = field(default_factory=dict[str, list[tuple[datetime, str]]])
    logbook: list[Json] = field(default_factory=list[Json])
    requests: list[tuple[str, str, dict[str, str], Any]] = field(default_factory=list[tuple[str, str, dict[str, str], Any]])
    commands: list[Json] = field(default_factory=list[Json])
    connections: int = 0
    status: int | None = None
    garbage: bool = False
    reject_calls: bool = False
    ws_auth_ok: bool = True
    ws_error: str | None = None
    ws_drop: bool = False
    ws_lines: list[Json] = field(default_factory=list[Json])

    def reset(self) -> None:
        fresh = Ha(url=self.url)
        self.__dict__.update(fresh.__dict__)

    def mutations(self) -> list[tuple[str, str]]:
        """The writes asked of the house over REST (method, path) and the WebSocket commands that change a registry."""
        rest = [(m, p) for m, p, _, _ in self.requests if m in ("POST", "DELETE")]
        socket = [("WS", str(c["type"])) for c in self.commands if re.search(r"/(create|update|delete|remove)", str(c["type"]))]
        return rest + socket

    def add(self, entity_id: str, state: str, name: str | None = None, *, area: str | None = None,
            device: str | None = None, aliases: list[str | None] | None = None, exposed: bool = False,
            changed: datetime | None = T0, registry: bool = True, **attributes: Any) -> None:
        shown = name or entity_id.split(".", 1)[1].replace("_", " ").title()
        body: Json = {"entity_id": entity_id, "state": state, "attributes": {"friendly_name": shown, **attributes},
                      "context": {"id": "01", "parent_id": None, "user_id": None}}
        if changed is not None:
            body["last_changed"] = body["last_updated"] = changed.isoformat()
        self.states[entity_id] = body
        if registry:
            self.entities[entity_id] = {"entity_id": entity_id, "name": None, "original_name": shown, "device_id": device,
                                        "area_id": area, "platform": entity_id.split(".", 1)[0] + "_integration",
                                        "disabled_by": None, "hidden_by": None, "aliases": list(aliases or []),
                                        "options": {"conversation": {"should_expose": exposed}} if exposed else {},
                                        "config_entry_id": None, "entity_category": None, "icon": None, "labels": []}

    def area(self, name: str, *, aliases: tuple[str, ...] = (), floor: str | None = None) -> str:
        area_id = slug(name)
        self.areas[area_id] = {"area_id": area_id, "name": name, "aliases": list(aliases), "floor_id": floor,
                               "icon": None, "labels": [], "picture": None}
        return area_id

    def floor(self, name: str, level: int = 0) -> str:
        floor_id = slug(name)
        self.floors[floor_id] = {"floor_id": floor_id, "name": name, "level": level, "aliases": [], "icon": None}
        return floor_id

    def label(self, name: str) -> str:
        label_id = slug(name)
        self.labels[label_id] = {"label_id": label_id, "name": name, "icon": None, "color": None, "description": None}
        return label_id

    def entry(self, domain: str, title: str, *, state: str = "loaded") -> str:
        entry_id = f"entry_{slug(title)}"
        self.entries[entry_id] = {"entry_id": entry_id, "domain": domain, "title": title, "state": state,
                                  "disabled_by": None, "source": "user"}
        return entry_id

    def device(self, name: str, *, area: str | None = None, entries: tuple[str, ...] = (), manufacturer: str | None = None,
               model: str | None = None, version: str | None = None) -> str:
        device_id = f"dev_{slug(name)}"
        self.devices[device_id] = {"id": device_id, "name": name, "name_by_user": None, "area_id": area,
                                   "manufacturer": manufacturer, "model": model, "sw_version": version,
                                   "config_entries": list(entries), "disabled_by": None}
        return device_id

    def service(self, domain: str, name: str, description: str = "", fields: dict[str, str] | None = None,
                response: str = "none", then: Callable[[Ha, Json], list[str]] | None = None, returns: Json | None = None) -> None:
        body: Json = {"name": name.replace("_", " ").title(), "description": description,
                      "fields": {k: {"description": v} for k, v in (fields or {}).items()}}
        if response != "none":
            body["response"] = {"optional": response == "optional"}
        self.services.setdefault(domain, {})[name] = body
        if then is not None:
            self.effects[f"{domain}.{name}"] = then
        if returns is not None:
            self.responses[f"{domain}.{name}"] = returns

    def put_config(self, kind: str, config_id: str, config: Json) -> None:
        """Store an automation or script as HA does: its file, and its entity (`automation.<alias slug>` carrying the
        config's `id`, `script.<id>`), which is how a house lists them."""
        self.drop_config(kind, config_id)
        self.configs[kind][config_id] = {**config, "id": config_id}
        alias = str(config["alias"])
        if kind == "automation":
            entity_id, n = f"automation.{slug(alias)}", 1
            while entity_id in self.states:
                n += 1
                entity_id = f"automation.{slug(alias)}_{n}"
            self.add(entity_id, "on", alias, registry=False, id=config_id, last_triggered=None)
        else:
            self.add(f"script.{config_id}", "off", alias, registry=False)

    def drop_config(self, kind: str, config_id: str) -> None:
        held = self.configs[kind].pop(config_id, None)
        if held is None:
            return
        if kind == "automation":
            for i in [i for i, s in self.states.items() if i.startswith("automation.") and s["attributes"].get("id") == config_id]:
                del self.states[i]
        else:
            self.states.pop(f"script.{config_id}", None)

    def names_of(self, entity_id: str) -> list[str]:
        """The names an entity answers to in Assist: its own only when its aliases keep the null."""
        row = self.entities[entity_id]
        mine = str(self.states[entity_id]["attributes"]["friendly_name"])
        return ([mine] if None in row["aliases"] else []) + [a for a in row["aliases"] if a is not None]


def light_on(ha: Ha, data: Json) -> list[str]:
    ids = _ids(data)
    for i in ids:
        ha.states[i]["state"] = "on"
    return ids


def light_off(ha: Ha, data: Json) -> list[str]:
    ids = _ids(data)
    for i in ids:
        ha.states[i]["state"] = "off"
    return ids


def _ids(data: Json) -> list[str]:
    got = data.get("entity_id", [])
    return [got] if isinstance(got, str) else list(got)
