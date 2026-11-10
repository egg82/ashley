"""`house_find`: what exists in the house and how it is set up, read from the house itself: its devices, entities,
areas, floors, labels and integrations, its automations, scripts and helpers (and one's config), the actions it offers
(and one's fields), and what an integration reports about its devices. Everything, whether or not the household lists it
for her by name. An answer holds every match or says it does not (`complete`), never a cut list.

The `tools.call` line carries the kind, how many matched, and which form of answer fit."""

from collections.abc import Mapping
from typing import Any

from ..inference.model import ToolSpec
from ..home_assistant.ha_json import is_list, is_object, listed, obj
from ..home_assistant.house import (CONFIG_KINDS, RECORD_KINDS, ActionInfo, ConfigItem, ConfigKind, House, Record,
                                    RecordKind)
from . import house_args as args
from .house_answer import Answer, Body, error, fit
from .house_look_config import HouseLookConfig
from .house_query import same_text, words_match

NAME = "house_find"
KINDS = (*RECORD_KINDS, *CONFIG_KINDS, "action", "diagnostics")
DESCRIPTION = (
    "Look up what exists in the house and how it is set up, from the house itself: everything, including what is not in "
    "the list of devices you were given. Use it before answering any question about a device the household has (what it "
    "is, its model or firmware, what it can do, whether it can be set up another way): the house knows its own devices, "
    "and general knowledge of the product does not. kind: device, entity, area, floor, label, integration (the house's "
    "integrations, with their ids), automation, script, helper, action (what you can do, with its fields), or "
    "diagnostics (what an integration reports about itself and its devices, by integration id). name narrows by words "
    "(every word must be in a record's name, aliases, area, maker, model or integration), area and domain by their "
    "values, id picks one: for an automation, script or helper it gives the config; for an action its fields. "
    "A device's record names its integration ids. When an answer is not complete, narrow it by what narrow_by says.")
PARAMETERS = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": list(KINDS)},
    "name": {"type": "string", "description": "Words from the name, an alias, the area, maker, model or integration."},
    "area": {"type": "string", "description": "An area's name."},
    "domain": {"type": "string", "description": "An entity's domain (light, sensor) or an integration's (esphome, hue)."},
    "id": {"type": "string", "description": "One record's id; for an action, domain.name; for diagnostics, the integration id."},
    "path": {"type": "string", "description": "For diagnostics or a config: dotted keys into it, to read less of a large one."}},
    "required": ["kind"]}
SPEC = ToolSpec(NAME, DESCRIPTION, PARAMETERS, reads=True, outside=False)
_ARGUMENTS = ("kind", "name", "area", "domain", "id", "path")


async def run(house: House, arguments: Mapping[str, object], config: HouseLookConfig) -> Answer:
    args.only(arguments, NAME, _ARGUMENTS)
    kind = args.required(arguments, "kind")
    if kind not in KINDS:
        raise ValueError(f"kind is one of {', '.join(KINDS)}")
    name, area, domain = args.text(arguments, "name"), args.text(arguments, "area"), args.text(arguments, "domain")
    one, path = args.text(arguments, "id"), args.text(arguments, "path")
    if kind == "diagnostics":
        return await _diagnostics(house, one, path, config)
    if kind == "action":
        return await _actions(house, name, domain, one, config)
    for config_kind in CONFIG_KINDS:
        if kind == config_kind:
            return await _configs(house, config_kind, name, one, path, config)
    for record_kind in RECORD_KINDS:
        if kind == record_kind:
            return await _records(house, record_kind, name, area, domain, one, config)
    raise ValueError(f"kind is one of {', '.join(KINDS)}")


async def _records(house: House, kind: RecordKind, name: str | None, area: str | None, domain: str | None,
                   one: str | None, config: HouseLookConfig) -> Answer:
    found = tuple(r for r in await house.records(kind) if _kept(r, name, area, domain, one))
    shown = [{"id": r.id, "name": r.name, **_present(r.fields)} for r in found]
    text, form = fit([
        {"kind": kind, "total": len(found), "complete": True, "records": shown},
        {"kind": kind, "total": len(found), "complete": True, "narrow_by": ["id"],
         "records": [{"id": r.id, "name": r.name} for r in found]},
        {"kind": kind, "total": len(found), "complete": False, "narrow_by": ["name", "area", "domain"]}], config.max_chars)
    return Answer(text, False, {"kind": kind, "matched": len(found), "form": form})


def _kept(record: Record, name: str | None, area: str | None, domain: str | None, one: str | None) -> bool:
    fields = record.fields
    if one is not None and record.id != one:
        return False
    if area is not None and not same_text(str(fields.get("area", "")), area):
        return False
    if domain is not None and not any(same_text(str(fields.get(k, "")), domain) for k in ("domain", "integration")):
        return False
    return name is None or words_match(name, _vocabulary(record))


def _vocabulary(record: Record) -> list[str]:
    f = record.fields
    aliases = f.get("aliases")
    extra = [str(f.get(k, "")) for k in ("area", "manufacturer", "model", "integration", "domain", "title")]
    return [record.name, *(aliases if isinstance(aliases, list) else []), *extra]


def _present(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The fields that say something: not empty, and a flag only when it is set."""
    return {k: v for k, v in fields.items() if v not in ("", [], None, False)}


async def _configs(house: House, kind: ConfigKind, name: str | None, one: str | None, path: str | None,
                   config: HouseLookConfig) -> Answer:
    if one is not None:
        got = await house.config(kind, one)
        if got is None:
            return Answer(fit([{"kind": kind, "id": one, "found": False}], config.max_chars)[0], False,
                          {"kind": kind, "matched": 0, "form": 0})
        return _drilled({"kind": kind, "id": one, "config": got}, "config", path, config, kind)
    items = tuple(i for i in await house.configs(kind) if name is None or words_match(name, [i.name, i.id]))
    text, form = fit([
        {"kind": kind, "total": len(items), "complete": True, "items": [_item(i) for i in items]},
        {"kind": kind, "total": len(items), "complete": False, "narrow_by": ["name"]}], config.max_chars)
    return Answer(text, False, {"kind": kind, "matched": len(items), "form": form})


def _item(item: ConfigItem) -> dict[str, str]:
    return {"id": item.id, "name": item.name}


async def _actions(house: House, name: str | None, domain: str | None, one: str | None,
                   config: HouseLookConfig) -> Answer:
    found = tuple(a for a in await house.actions() if _fits(a, name, domain, one))
    if one is not None and found:
        a = found[0]
        text, form = fit([{"kind": "action", "id": a.name, "description": a.description, "returns": a.response,
                           "fields": dict(a.fields)}, {"kind": "action", "id": a.name, "returns": a.response,
                                                       "fields": list(a.fields)}], config.max_chars)
        return Answer(text, False, {"kind": "action", "matched": 1, "form": form})
    text, form = fit([
        {"kind": "action", "total": len(found), "complete": True,
         "actions": [{"id": a.name, "description": a.description} for a in found]},
        {"kind": "action", "total": len(found), "complete": True, "narrow_by": ["id"], "actions": [a.name for a in found]},
        {"kind": "action", "total": len(found), "complete": False, "narrow_by": ["name", "domain"]}], config.max_chars)
    return Answer(text, False, {"kind": "action", "matched": len(found), "form": form})


def _fits(action: ActionInfo, name: str | None, domain: str | None, one: str | None) -> bool:
    if one is not None:
        return action.name == one
    if domain is not None and action.name.split(".", 1)[0] != domain:
        return False
    return name is None or words_match(name, [action.name.replace(".", " "), action.description])


async def _diagnostics(house: House, one: str | None, path: str | None, config: HouseLookConfig) -> Answer:
    if one is None:
        return error("diagnostics needs the integration id (a device's record names it, or kind integration lists them)")
    got = await house.diagnostics(one)
    if got is None:
        return Answer(fit([{"kind": "diagnostics", "id": one, "reported": False}], config.max_chars)[0], False,
                      {"kind": "diagnostics", "matched": 0, "form": 0})
    return _drilled({"kind": "diagnostics", "id": one, "report": got}, "report", path, config, "diagnostics")


def _drilled(body: Body, key: str, path: str | None, config: HouseLookConfig, kind: str) -> Answer:
    """`body` with `key`'s value, or what `path` (dotted keys) reaches in it; when that is too large, its keys with each
    value's size, so she narrows by `path` instead of reading a cut."""
    value: object = body[key]
    for step in (path.split(".") if path else []):
        inner = obj(value)
        if step not in inner:
            return error(f"path {step} is not in it")
        value = inner[step]
    shown: Body = {**body, key: value, **({"path": path} if path else {})}
    outline: Body = {**{k: v for k, v in shown.items() if k != key}, "complete": False, "narrow_by": ["path"],
                     key: {k: _size(v) for k, v in obj(value).items()} if is_object(value) else _size(value)}
    text, form = fit([{**shown, "complete": True}, outline], config.max_chars)
    return Answer(text, False, {"kind": kind, "matched": 1, "form": form})


def _size(value: object) -> str:
    if is_object(value):
        return f"object of {len(obj(value))}"
    if is_list(value):
        return f"list of {len(listed(value))}"
    return f"{type(value).__name__} of {len(str(value))} characters"
