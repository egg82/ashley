"""Home Assistant's registries (WebSocket) mapped onto the House port's neutral records: what exists in the house, which
area each thing is in (its own, else its device's), and the names it answers to. Entity aliases are not in the
registry's list, so they are fetched for the entities that have a state with `config/entity_registry/get_entries`."""

import asyncio
from collections.abc import Mapping, Sequence

from .ha_json import JsonObject, moment, names, obj, rows, text
from .ha_socket import Commands
from .house import Record, RecordKind, State

_LISTS: Mapping[str, str] = {
    "entity": "config/entity_registry/list", "device": "config/device_registry/list",
    "area": "config/area_registry/list", "floor": "config/floor_registry/list",
    "label": "config/label_registry/list", "integration": "config_entries/get"}


class Registries:
    def __init__(self, commands: Commands) -> None:
        self._commands = commands

    async def rows(self, kind: RecordKind) -> list[JsonObject]:
        return rows(await self._commands.run({"type": _LISTS[kind]}))

    async def records(self, kind: RecordKind) -> tuple[Record, ...]:
        found = await self.rows(kind)
        if kind == "entity":
            return await self._entities(found)
        if kind == "device":
            areas, entries = await asyncio.gather(self._area_names(), self.rows("integration"))
            return tuple(_device(r, areas, {text(e.get("entry_id")): e for e in entries}) for r in found)
        if kind == "area":
            floors = {text(f.get("floor_id")): text(f.get("name")) for f in await self.rows("floor")}
            return tuple(_area(r, floors) for r in found)
        return tuple(_simple(kind, r) for r in found)

    async def states(self, raw: object) -> tuple[State, ...]:
        """The states `raw` (the REST `/api/states` body) holds, each with its area and the names it answers to."""
        entities, devices, areas = await asyncio.gather(self.rows("entity"), self.rows("device"), self.rows("area"))
        entity_of = {text(e.get("entity_id")): e for e in entities}
        device_of = {text(d.get("id")): d for d in devices}
        area_of = {text(a.get("area_id")): a for a in areas}
        found = [s for s in rows(raw) if text(s.get("entity_id"))]
        aliases = await self._aliases([text(s.get("entity_id")) for s in found if text(s.get("entity_id")) in entity_of])
        return tuple(_state(s, entity_of, device_of, area_of, aliases) for s in found)

    async def _area_names(self) -> dict[str, str]:
        return {text(a.get("area_id")): text(a.get("name")) for a in await self.rows("area")}

    async def _entities(self, found: list[JsonObject]) -> tuple[Record, ...]:
        areas, devices = await asyncio.gather(self._area_names(), self.rows("device"))
        device_of = {text(d.get("id")): d for d in devices}
        aliases = await self._aliases([text(r.get("entity_id")) for r in found])
        return tuple(_entity(r, areas, device_of, aliases.get(text(r.get("entity_id")), ())) for r in found)

    async def _aliases(self, ids: Sequence[str]) -> dict[str, tuple[str, ...]]:
        got = obj(await self._commands.run({"type": "config/entity_registry/get_entries", "entity_ids": list(ids)}))
        return {k: names(obj(v).get("aliases")) for k, v in got.items()}


def _state(raw: JsonObject, entity_of: Mapping[str, JsonObject], device_of: Mapping[str, JsonObject],
           area_of: Mapping[str, JsonObject], aliases: Mapping[str, tuple[str, ...]]) -> State:
    entity_id = text(raw.get("entity_id"))
    registered = entity_of.get(entity_id, {})
    device = device_of.get(text(registered.get("device_id")), {})
    area = area_of.get(text(registered.get("area_id")) or text(device.get("area_id")), {})
    attributes = obj(raw.get("attributes"))
    return State(entity_id, text(attributes.get("friendly_name")) or entity_id, text(raw.get("state")),
                 entity_id.split(".", 1)[0], text(area.get("name")) or None, attributes,
                 moment(raw.get("last_changed")), aliases.get(entity_id, ()), names(area.get("aliases")),
                 _exposed(registered))


def _exposed(row: JsonObject) -> bool:
    return obj(obj(row.get("options")).get("conversation")).get("should_expose") is True


def _entity_name(row: JsonObject, device: JsonObject) -> str:
    """The name the house shows for it: its own, else its original name, after its device's name when it is named as a
    part of one."""
    own = text(row.get("name"))
    if own:
        return own
    original = text(row.get("original_name"))
    owner = text(device.get("name_by_user")) or text(device.get("name"))
    return f"{owner} {original}".strip() if row.get("has_entity_name") is True and owner else original


def _entity(row: JsonObject, areas: Mapping[str, str], device_of: Mapping[str, JsonObject],
            aliases: tuple[str, ...]) -> Record:
    device = device_of.get(text(row.get("device_id")), {})
    entity_id = text(row.get("entity_id"))
    name = _entity_name(row, device)
    fields: JsonObject = {
        "name": name, "domain": entity_id.split(".", 1)[0], "device": text(row.get("device_id")),
        "area": areas.get(text(row.get("area_id")) or text(device.get("area_id")), ""),
        "integration": text(row.get("platform")), "aliases": list(aliases), "disabled": row.get("disabled_by") is not None,
        "hidden": row.get("hidden_by") is not None, "exposed": _exposed(row),
        "integration_id": text(row.get("config_entry_id"))}
    return Record("entity", entity_id, name or entity_id, fields)


def _device(row: JsonObject, areas: Mapping[str, str], entries: Mapping[str, JsonObject]) -> Record:
    name = text(row.get("name_by_user")) or text(row.get("name"))
    ids = names(row.get("config_entries"))
    domains = [text(entries.get(i, {}).get("domain")) for i in ids]
    fields: JsonObject = {
        "name": name, "area": areas.get(text(row.get("area_id")), ""), "manufacturer": text(row.get("manufacturer")),
        "model": text(row.get("model")), "version": text(row.get("sw_version")),
        "integration": ", ".join(d for d in domains if d), "disabled": row.get("disabled_by") is not None,
        "integration_ids": list(ids)}
    return Record("device", text(row.get("id")), name, fields)


def _area(row: JsonObject, floors: Mapping[str, str]) -> Record:
    name = text(row.get("name"))
    return Record("area", text(row.get("area_id")), name, {
        "name": name, "floor": floors.get(text(row.get("floor_id")), ""), "aliases": list(names(row.get("aliases")))})


def _simple(kind: RecordKind, row: JsonObject) -> Record:
    """A floor, label or integration."""
    if kind == "floor":
        name = text(row.get("name"))
        return Record("floor", text(row.get("floor_id")), name, {
            "name": name, "level": row.get("level"), "aliases": list(names(row.get("aliases")))})
    if kind == "label":
        name = text(row.get("name"))
        return Record("label", text(row.get("label_id")), name, {"name": name, "description": text(row.get("description"))})
    title = text(row.get("title"))
    return Record("integration", text(row.get("entry_id")), title, {
        "title": title, "domain": text(row.get("domain")), "state": text(row.get("state")),
        "disabled": row.get("disabled_by") is not None})
