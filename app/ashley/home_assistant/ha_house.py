"""The House port (`house.House`) over Home Assistant: states, history, logbook and actions through the REST API,
registries and helpers through the WebSocket API (`ha_registry`, `ha_changes`). Needs an admin user's token. Tunables are
data, `house.json`. Logs nothing itself; her tools log what they ask."""

import asyncio
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote

from .client import HomeAssistant
from .ha_changes import Changes
from .ha_json import JsonObject, is_list, is_object, listed, moment, obj, rows, text
from .ha_registry import Registries
from .ha_rest import Rest
from .ha_socket import Commands
from .house import (ActionInfo, ConfigItem, ConfigKind, House, HouseRejected, HouseUnavailable, LogEntry, Performed,
                    Reading, Record, RecordKind, Series, State, Window)
from .house_settings import HouseSettings


class HaHouse(House):
    def __init__(self, home_assistant: HomeAssistant, settings: HouseSettings) -> None:
        commands = Commands(home_assistant, settings)
        self._settings = settings
        self._rest = Rest(home_assistant, settings)
        self._registries = Registries(commands)
        self._changes = Changes(self._rest, commands)

    def offered(self) -> bool:
        return True

    async def states(self) -> tuple[State, ...]:
        return await self._registries.states(await self._rest.get("/api/states", "states"))

    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        return await self._registries.records(kind)

    async def history(self, window: Window) -> tuple[Series, ...]:
        if not window.ids:
            raise HouseRejected("a history names the things it is of")
        got = await self._rest.get(f"/api/history/period/{quote(window.start.isoformat(), safe='')}", "history", {
            "filter_entity_id": ",".join(window.ids), "end_time": window.end.isoformat(), "minimal_response": "1",
            "no_attributes": "1"})
        if not is_list(got):
            raise HouseUnavailable("history: not a list")
        return tuple(Series(text(series[0].get("entity_id")), _readings(series)) for series in
                     (rows(group) for group in listed(got)) if series)

    async def logbook(self, window: Window) -> tuple[LogEntry, ...]:
        entries: list[LogEntry] = []
        for entity in window.ids or (None,):
            params = {"end_time": window.end.isoformat(), **({} if entity is None else {"entity": entity})}
            got = await self._rest.get(f"/api/logbook/{quote(window.start.isoformat(), safe='')}", "logbook", params)
            if not is_list(got):
                raise HouseUnavailable("logbook: not a list")
            entries += [e for e in (_entry(r) for r in rows(got)) if e is not None]
        return tuple(sorted(entries, key=lambda e: e.at))

    async def actions(self) -> tuple[ActionInfo, ...]:
        got = await self._rest.get("/api/services", "actions")
        if not is_list(got):
            raise HouseUnavailable("actions: not a list")
        return tuple(_action(text(d.get("domain")), name, obj(spec)) for d in rows(got) if text(d.get("domain"))
                     for name, spec in obj(d.get("services")).items())

    async def perform(self, action: str, ids: tuple[str, ...], data: Mapping[str, Any]) -> Performed:
        domain, _, name = action.partition(".")
        if not domain or not name:
            raise HouseRejected("an action is domain.name")
        body = {**data, **({"entity_id": list(ids)} if ids else {})}
        path = f"/api/services/{quote(domain, safe='')}/{quote(name, safe='')}"
        try:
            got = await self._rest.send("POST", path, "action", body)
        except HouseRejected:
            if not await self._returns_only(action):
                raise
            got = await self._rest.send("POST", path, "action", body, {"return_response": "1"})
        return _performed(got)

    async def _returns_only(self, action: str) -> bool:
        return any(a.name == action and a.response == "only" for a in await self.actions())

    async def configs(self, kind: ConfigKind) -> tuple[ConfigItem, ...]:
        return await self._changes.configs(kind)

    async def config(self, kind: ConfigKind, config_id: str) -> Mapping[str, Any] | None:
        return await self._changes.config(kind, config_id)

    async def write_config(self, kind: ConfigKind, config_id: str | None, config: Mapping[str, Any]) -> str:
        return await self._changes.write_config(kind, config_id, config)

    async def delete_config(self, kind: ConfigKind, config_id: str) -> bool:
        return await self._changes.delete_config(kind, config_id)

    async def shown_as(self, kind: ConfigKind, config_id: str) -> str | None:
        for attempt in range(self._settings.entity_tries):
            if attempt:
                await asyncio.sleep(self._settings.entity_wait_s)
            thing = next((i.thing for i in await self.configs(kind) if i.id == config_id and i.thing), None)
            if thing is not None:
                return thing
        return None

    async def set_enabled(self, thing: str, enabled: bool) -> None:
        service = "turn_on" if enabled else "turn_off"
        try:
            await self._rest.send("POST", f"/api/services/automation/{service}", service, {"entity_id": thing})
        except HouseRejected as e:
            raise HouseUnavailable(f"{service}: refused") from e

    async def create_record(self, kind: RecordKind, fields: Mapping[str, Any]) -> str:
        return await self._changes.create_record(kind, fields)

    async def update_record(self, kind: RecordKind, record_id: str, fields: Mapping[str, Any]) -> None:
        await self._changes.update_record(kind, record_id, fields)

    async def delete_record(self, kind: RecordKind, record_id: str) -> None:
        await self._changes.delete_record(kind, record_id)

    async def diagnostics(self, integration_id: str) -> Mapping[str, Any] | None:
        got = await self._rest.get_or_none(f"/api/diagnostics/config_entry/{quote(integration_id, safe='')}", "diagnostics")
        return obj(got) if is_object(got) else None


def _readings(series: list[JsonObject]) -> tuple[Reading, ...]:
    found = [(moment(r.get("last_changed") or r.get("last_updated")), r) for r in series]
    return tuple(Reading(at, str(r["state"])) for at, r in found if at is not None and "state" in r)


def _entry(row: JsonObject) -> LogEntry | None:
    at = moment(row.get("when"))
    if at is None:
        return None
    return LogEntry(at, text(row.get("entity_id")) or None, text(row.get("name")),
                    text(row.get("message")) or text(row.get("state")))


def _action(domain: str, name: str, spec: JsonObject) -> ActionInfo:
    response = spec.get("response")
    mode: Literal["none", "optional", "only"] = "none"
    if is_object(response):
        mode = "optional" if obj(response).get("optional") else "only"
    described = {key: text(obj(field).get("description")) for key, field in obj(spec.get("fields")).items()}
    return ActionInfo(f"{domain}.{name}", text(spec.get("description")), described, mode)


def _performed(got: object) -> Performed:
    if is_object(got):
        body = obj(got)
        response = body.get("service_response")
        return Performed(_changed(body.get("changed_states")), obj(response) if is_object(response) else None)
    return Performed(_changed(got))


def _changed(raw: object) -> tuple[State, ...]:
    out: list[State] = []
    for s in rows(raw):
        entity = text(s.get("entity_id"))
        if entity:
            attributes = obj(s.get("attributes"))
            out.append(State(entity, text(attributes.get("friendly_name")) or entity, text(s.get("state")),
                             entity.split(".", 1)[0], None, attributes, moment(s.get("last_changed"))))
    return tuple(out)
