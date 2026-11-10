"""The House adapter's configuration reads and writes over Home Assistant's REST and WebSocket APIs: automation and
script configs (REST), helpers and the registries (WebSocket), and removing an integration. The neutral field names of
`house.py` are mapped to Home Assistant's here; which of these an operation needs a person's OK for is not decided
here."""

import asyncio
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from .ha_json import JsonObject, is_object, listed, obj, rows, text
from .ha_rest import Rest
from .ha_socket import Commands
from .house import ConfigItem, ConfigKind, HouseRejected, RecordKind

HELPERS = ("input_boolean", "input_number", "input_text", "input_select", "input_datetime", "input_button", "counter",
           "timer", "schedule")
_FILES: Mapping[str, str] = {"automation": "/api/config/automation/config/", "script": "/api/config/script/config/"}
_REGISTRY: Mapping[str, str] = {"entity": "config/entity_registry", "device": "config/device_registry",
                                "area": "config/area_registry", "floor": "config/floor_registry",
                                "label": "config/label_registry"}
_ID_KEY: Mapping[str, str] = {"entity": "entity_id", "device": "device_id", "area": "area_id", "floor": "floor_id",
                              "label": "label_id"}
_DISABLED = {"disabled": "disabled_by", "hidden": "hidden_by"}
_SETTABLE: Mapping[str, frozenset[str]] = {
    "entity": frozenset({"name", "aliases", "area", "disabled", "hidden", "exposed"}),
    "device": frozenset({"name", "area", "disabled"}), "area": frozenset({"name", "aliases", "floor"}),
    "floor": frozenset({"name", "level", "aliases"}), "label": frozenset({"name", "description"})}


class Changes:
    def __init__(self, rest: Rest, commands: Commands) -> None:
        self._rest = rest
        self._commands = commands

    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        if kind == "helper":
            lists = await asyncio.gather(*(self._commands.run({"type": f"{t}/list"}) for t in HELPERS))
            return tuple(ConfigItem(f"{t}:{text(h.get('id'))}", text(h.get("name")) or text(h.get("id")))
                         for t, items in zip(HELPERS, lists, strict=True) for h in rows(items) if text(h.get("id")))
        states = rows(await self._rest.get("/api/states", f"list {kind}"))
        found = [s for s in states if text(s.get("entity_id")).startswith(kind + ".")]
        return tuple(ConfigItem(_config_id(kind, s), text(obj(s.get("attributes")).get("friendly_name")) or text(s.get("entity_id")))
                     for s in found if _config_id(kind, s))

    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        if kind == "helper":
            helper, _, helper_id = config_id.partition(":")
            if helper not in HELPERS:
                return None
            items = rows(await self._commands.run({"type": f"{helper}/list"}))
            return next(({"type": helper, **h} for h in items if h.get("id") == helper_id), None)
        got = await self._rest.get_or_none(_FILES[kind] + quote(config_id, safe=""), f"read {kind}")
        return obj(got) if is_object(got) else None

    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        if kind == "helper":
            return await self._write_helper(config_id, config)
        made = config_id or await self._free_id(kind, text(config.get("alias")))
        await self._rest.send("POST", _FILES[kind] + quote(made, safe=""), f"write {kind}", dict(config))
        return made

    async def _free_id(self, kind: ConfigKind, alias: str) -> str:
        """An id for a new automation or script, from its alias, that no existing one has (a write replaces the config with
        its id, so a new one never takes an id in use)."""
        base = re.sub(r"[^a-z0-9]+", "_", alias.casefold()).strip("_")[:60]
        if not base:
            raise HouseRejected(f"a new {kind} needs an alias to name it by")
        candidate, number = base, 1
        while await self.config(kind, candidate) is not None:
            number += 1
            candidate = f"{base}_{number}"
        return candidate

    async def _write_helper(self, config_id: str | None, config: Mapping[str, Any]) -> str:
        helper = config.get("type") if config_id is None else config_id.partition(":")[0]
        if not isinstance(helper, str) or helper not in HELPERS:
            raise HouseRejected(f"a helper's type is one of {', '.join(HELPERS)}")
        fields = {k: v for k, v in config.items() if k != "type"}
        if config_id is None:
            made = obj(await self._commands.run({"type": f"{helper}/create", **fields}))
            return f"{helper}:{text(made.get('id'))}"
        await self._commands.run({"type": f"{helper}/update", f"{helper}_id": config_id.partition(":")[2], **fields})
        return config_id

    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        if kind == "helper":
            helper, _, helper_id = config_id.partition(":")
            if helper not in HELPERS or await self.config(kind, config_id) is None:
                return False
            await self._commands.run({"type": f"{helper}/delete", f"{helper}_id": helper_id})
            return True
        return await self._rest.delete(_FILES[kind] + quote(config_id, safe=""), f"delete {kind}")

    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        if kind not in ("area", "floor", "label"):
            raise HouseRejected(f"a {kind} cannot be created")
        made = obj(await self._commands.run({"type": f"{_REGISTRY[kind]}/create", **await self._mapped(kind, fields)}))
        return text(made.get(_ID_KEY[kind]))

    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        if kind not in _REGISTRY:
            raise HouseRejected(f"a {kind} cannot be changed")
        unknown = sorted(set(fields) - _SETTABLE[kind])
        if unknown:
            raise HouseRejected(f"a {kind} has no {', '.join(unknown)} to set; it has {', '.join(sorted(_SETTABLE[kind]))}")
        mapped = await self._mapped(kind, fields)
        if "should_expose" in mapped:
            await self._commands.run({"type": "homeassistant/expose_entity", "assistants": ["conversation"],
                                      "entity_ids": [record_id], "should_expose": mapped.pop("should_expose")})
        if mapped:
            await self._commands.run({"type": f"{_REGISTRY[kind]}/update", _ID_KEY[kind]: record_id, **mapped})

    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        if kind == "integration":
            if not await self._rest.delete("/api/config/config_entries/entry/" + quote(record_id, safe=""),
                                           "remove integration", missing=(404,)):
                raise HouseRejected("no such integration")
        elif kind == "device":
            await self._remove_device(record_id)
        elif kind in _REGISTRY:
            command = "remove" if kind == "entity" else "delete"
            await self._commands.run({"type": f"{_REGISTRY[kind]}/{command}", _ID_KEY[kind]: record_id})
        else:
            raise HouseRejected(f"a {kind} cannot be deleted")

    async def _remove_device(self, device_id: str) -> None:
        device = next((d for d in rows(await self._commands.run({"type": "config/device_registry/list"}))
                       if d.get("id") == device_id), None)
        if device is None:
            raise HouseRejected("no such device")
        for entry in listed(device.get("config_entries")):
            await self._commands.run({"type": "config/device_registry/remove_config_entry",
                                      "device_id": device_id, "config_entry_id": entry})

    async def _mapped(self, kind: str, fields: Mapping[str, Any]) -> dict[str, Any]:
        """Home Assistant's names and ids for the neutral `fields`: an area or floor by name becomes its id. An entity's
        aliases keep the entity's own name (`None` first), as the house's own editor writes them."""
        out: dict[str, Any] = {}
        for key, value in fields.items():
            if key in _DISABLED:
                out[_DISABLED[key]] = "user" if value is True else None
            elif key == "exposed":
                out["should_expose"] = value is True
            elif key in ("area", "floor"):
                out[f"{key}_id"] = await self._registry_id(key, value)
            elif key == "aliases" and kind == "entity":
                out[key] = [None, *listed(value)]
            elif key == "name" and kind == "device":
                out["name_by_user"] = value
            else:
                out[key] = value
        return out

    async def _registry_id(self, kind: str, name: object) -> str | None:
        if name in (None, ""):
            return None
        wanted = str(name).casefold()
        for row in rows(await self._commands.run({"type": f"{_REGISTRY[kind]}/list"})):
            if row.get(_ID_KEY[kind]) == name or text(row.get("name")).casefold() == wanted:
                return text(row.get(_ID_KEY[kind]))
        raise HouseRejected(f"no {kind} named {name}")


def _config_id(kind: str, state: JsonObject) -> str:
    if kind == "automation":
        return text(obj(state.get("attributes")).get("id"))
    return text(state.get("entity_id")).split(".", 1)[1]
