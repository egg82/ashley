"""The stand-in's WebSocket half: the auth handshake and the command set for registries, helpers and entries."""

from __future__ import annotations

from typing import Any

from hag_state_support import Ha, Json, slug
from starlette.websockets import WebSocket, WebSocketDisconnect


def _ok(result: Any = None) -> Json:
    return {"success": True, "result": result}


def _fail(code: str, message: str) -> Json:
    return {"success": False, "error": {"code": code, "message": message}}


_REGISTRIES = {"area": "areas", "floor": "floors", "label": "labels"}
_ID = {"area": "area_id", "floor": "floor_id", "label": "label_id"}
_HELPERS = ("input_boolean", "input_number", "input_text", "input_select", "input_datetime", "input_button", "counter",
            "timer", "schedule")


def _command(ha: Ha, command: Json) -> Json:
    if ha.ws_error is not None and command["type"] != "auth":
        return _fail(ha.ws_error, "refused")
    kind = str(command["type"])
    parts = kind.split("/")
    if kind == "config/entity_registry/list":
        return _ok([_entity_row(r) for r in ha.entities.values()])
    if kind == "config/entity_registry/get_entries":
        return _ok({i: _entity_row(ha.entities[i]) if i in ha.entities else None for i in command["entity_ids"]})
    if kind == "config/entity_registry/update":
        return _update(ha.entities, command, "entity_id", ("name", "aliases", "area_id", "disabled_by", "hidden_by", "icon", "labels", "new_entity_id"))
    if kind == "config/entity_registry/remove":
        return _remove(ha.entities, command["entity_id"], ha)
    if kind == "homeassistant/expose_entity":
        for i in command["entity_ids"]:
            if i not in ha.entities:
                return _fail("not_found", "Entity not found")
            ha.entities[i]["options"] = {"conversation": {"should_expose": bool(command["should_expose"])}}
        return _ok()
    if kind == "homeassistant/expose_entity/list":
        return _ok({"exposed_entities": {i: {"conversation": bool(r["options"].get("conversation", {}).get("should_expose"))}
                                         for i, r in ha.entities.items()}})
    if kind == "config/device_registry/list":
        return _ok(list(ha.devices.values()))
    if kind == "config/device_registry/update":
        return _update(ha.devices, command, "device_id", ("name_by_user", "area_id", "disabled_by", "labels"))
    if kind == "config/device_registry/remove_config_entry":
        return _remove_from_device(ha, command)
    if len(parts) == 3 and parts[0] == "config" and parts[1].endswith("_registry") and parts[1][:-9] in _REGISTRIES:
        return _registry(ha, parts[1][:-9], parts[2], command)
    if kind == "config_entries/get":
        return _ok(list(ha.entries.values()))
    if kind == "get_states":
        return _ok(list(ha.states.values()))
    if kind == "get_services":
        return _ok(ha.services)
    if len(parts) == 2 and parts[0] in _HELPERS:
        return _helper(ha, parts[0], parts[1], command)
    return _fail("unknown_command", "Unknown command.")


def _entity_row(row: Json) -> Json:
    return dict(row)


def _update(table: dict[str, Json], command: Json, key: str, allowed: tuple[str, ...]) -> Json:
    row = table.get(command[key])
    if row is None:
        return _fail("not_found", "Entry not found")
    extra = set(command) - set(allowed) - {"id", "type", key}
    if extra:
        return _fail("invalid_format", f"extra keys not allowed @ data[{sorted(extra)[0]!r}]")
    for field_name in allowed:
        if field_name in command:
            row[field_name] = command[field_name]
    return _ok({"entity_entry": row, "device": row, "area": row, "floor": row, "label": row})


def _remove(table: dict[str, Json], key: str, ha: Ha) -> Json:
    if key not in table:
        return _fail("not_found", "Entity not found")
    del table[key]
    ha.states.pop(key, None)
    return _ok()


def _remove_from_device(ha: Ha, command: Json) -> Json:
    row = ha.devices.get(command["device_id"])
    if row is None or command["config_entry_id"] not in row["config_entries"]:
        return _fail("home_assistant_error", "Config entry not in device")
    row["config_entries"].remove(command["config_entry_id"])
    if not row["config_entries"]:
        del ha.devices[command["device_id"]]
        for entity in [e for e, r in ha.entities.items() if r["device_id"] == command["device_id"]]:
            del ha.entities[entity]
            ha.states.pop(entity, None)
    return _ok({"config_entries": row["config_entries"]})


def _registry(ha: Ha, kind: str, verb: str, command: Json) -> Json:
    table: dict[str, Json] = getattr(ha, _REGISTRIES[kind])
    key = _ID[kind]
    if verb == "list":
        return _ok(list(table.values()))
    if verb == "create":
        if not command.get("name"):
            return _fail("invalid_format", "name required")
        new = slug(str(command["name"]))
        if new in table:
            return _fail("home_assistant_error", "The name is already in use")
        base: Json = {key: new, "name": command["name"], "aliases": [], "icon": None}
        table[new] = {**base, **{k: v for k, v in command.items() if k not in ("id", "type")}}
        return _ok(table[new])
    if verb == "update":
        return _update(table, command, key, ("name", "aliases", "floor_id", "level", "icon", "color", "description", "labels", "picture"))
    if verb == "delete":
        if command[key] not in table:
            return _fail("not_found", "Entry not found")
        del table[command[key]]
        return _ok()
    return _fail("unknown_command", "Unknown command.")


def _helper(ha: Ha, kind: str, verb: str, command: Json) -> Json:
    table = ha.helpers.setdefault(kind, {})
    key = f"{kind}_id"
    if verb == "list":
        return _ok(list(table.values()))
    if verb == "create":
        if not command.get("name"):
            return _fail("invalid_format", "name required")
        new = slug(str(command["name"]))
        table[new] = {"id": new, **{k: v for k, v in command.items() if k not in ("id", "type")}}
        return _ok(table[new])
    if command.get(key) not in table:
        return _fail("not_found", "Unable to find")
    if verb == "update":
        table[command[key]].update({k: v for k, v in command.items() if k not in ("id", "type", key)})
        return _ok(table[command[key]])
    if verb == "delete":
        del table[command[key]]
        return _ok()
    return _fail("unknown_command", "Unknown command.")


async def websocket(ha: Ha, socket: WebSocket) -> None:
    await socket.accept()
    ha.connections += 1
    if ha.ws_drop:
        await socket.close()
        return
    await socket.send_json({"type": "auth_required", "ha_version": "2026.10.4"})
    try:
        auth = await socket.receive_json()
        if auth.get("access_token") != ha.token or not ha.ws_auth_ok:
            await socket.send_json({"type": "auth_invalid", "message": "Invalid access token or password"})
            await socket.close()
            return
        await socket.send_json({"type": "auth_ok", "ha_version": "2026.10.4"})
        while True:
            command = await socket.receive_json()
            ha.commands.append({k: v for k, v in command.items() if k != "id"})
            for line in ha.ws_lines:
                await socket.send_json({**line, "id": command["id"]})
            await socket.send_json({"id": command["id"], "type": "result", **_command(ha, command)})
    except WebSocketDisconnect:
        return
