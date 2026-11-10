"""What a connection's person can set on it, declared by its kind as data (`ConnectionKind.settings`, Type Object) and
checked by `validate`. A setting is a named value of one `Field` shape; `decides` says what the setting changes in how
she behaves: `taint`, `tier` and `read` settings widen or narrow what she trusts, asks about or counts as a change, so only
a person writes them (`settings_write`), `plain` ones are preferences.

A value is JSON: a list of ids (`EntityList`, `ActionList`) or an object from a declared action to a list of ids
(`EntityListPerAction`). The service's own catalogue is advisory: `domains` filters what the room offers, and an id
the service does not list now is kept, since a device may only be offline."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

SettingValue = list[str] | dict[str, list[str]]
SettingValues = Mapping[str, SettingValue]
"""A connection's settings by key. A key not present is empty: nothing trusted, nothing listed."""

MAX_IDS = 200
_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


@dataclass(frozen=True)
class EntityList:
    """A list of the service's entities (`domain.object_id`), picked from those of `domains`."""

    domains: tuple[str, ...]


@dataclass(frozen=True)
class ActionList:
    """A list of the service's actions (`domain.name`), picked from those of `domains`."""

    domains: tuple[str, ...]


@dataclass(frozen=True)
class EntityListPerAction:
    """For each of `actions`, a list of entities picked from those of `domains`."""

    actions: tuple[str, ...]
    domains: tuple[str, ...]


Field = EntityList | ActionList | EntityListPerAction
Decides = Literal["taint", "tier", "read", "plain"]


@dataclass(frozen=True)
class Setting:
    """One setting of a kind: `key` stores it."""

    key: str
    field: Field
    decides: Decides


Reason = Literal["unknown_key", "wrong_shape", "bad_id", "too_many"]


class SettingsInvalid(Exception):
    """A value the kind's schema does not allow: the `key` it was given under and why."""

    def __init__(self, key: str, reason: Reason) -> None:
        super().__init__(key, reason)
        self.key = key
        self.reason: Reason = reason


def validate(settings: tuple[Setting, ...], values: SettingValues) -> dict[str, SettingValue]:
    """`values` as stored: each key declared by `settings`, each value of its field's shape, every id of the shape
    `domain.name`, lists without repeats and within `MAX_IDS`. A key with an empty value is dropped. Raises
    SettingsInvalid naming the first key that fails."""
    declared = {s.key: s for s in settings}
    out: dict[str, SettingValue] = {}
    for key, value in values.items():
        setting = declared.get(key)
        if setting is None:
            raise SettingsInvalid(key, "unknown_key")
        checked = _checked(key, setting.field, value)
        if checked:
            out[key] = checked
    return out


def _checked(key: str, field: Field, value: object) -> SettingValue:
    loose: Any = value
    if isinstance(field, EntityListPerAction):
        if not isinstance(value, dict):
            raise SettingsInvalid(key, "wrong_shape")
        pairs: dict[object, object] = dict(loose)
        per: dict[str, list[str]] = {}
        for action, ids in pairs.items():
            if not isinstance(action, str) or action not in field.actions:
                raise SettingsInvalid(key, "bad_id")
            if ids:
                per[action] = _ids(key, ids)
        return per
    if isinstance(value, dict):
        raise SettingsInvalid(key, "wrong_shape")
    return _ids(key, value)


def _ids(key: str, value: object) -> list[str]:
    loose: Any = value
    if not isinstance(value, list):
        raise SettingsInvalid(key, "wrong_shape")
    ids: list[object] = list(loose)
    if len(ids) > MAX_IDS:
        raise SettingsInvalid(key, "too_many")
    named = [i for i in ids if isinstance(i, str) and _ID.match(i)]
    if len(named) != len(ids):
        raise SettingsInvalid(key, "bad_id")
    return list(dict.fromkeys(named))
