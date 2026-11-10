"""The wire models of a connection's settings (`ashley.api.connection_settings`). The schema a kind declares is served
beside the values, so the room draws every setting from data and holds no copy of a kind's list."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .models import Person


class EntityListField(BaseModel):
    """A list of the service's entities, picked from those of `domains` (any domain when empty)."""

    type: Literal["entity_list"]
    domains: list[str]


class ActionListField(BaseModel):
    """A list of the service's actions, picked from those of `domains`."""

    type: Literal["action_list"]
    domains: list[str]


class EntityPerActionField(BaseModel):
    """For each of `for_actions`, a list of entities picked from those of `domains`."""

    type: Literal["entity_per_action"]
    for_actions: list[str]
    domains: list[str]


SettingField = Annotated[EntityListField | ActionListField | EntityPerActionField, Field(discriminator="type")]


class SettingInfo(BaseModel):
    """One setting a kind declares. `decides` is what it changes in how she behaves: `taint`, `tier` and `read` settings
    change what she trusts, asks about or counts as a change; `plain` ones are preferences."""

    key: str
    field: SettingField
    decides: Literal["taint", "tier", "read", "plain"]


class ActionIds(BaseModel):
    """The `ids` picked for one `action` of an entity-per-action setting."""

    action: str
    ids: list[str]


class SettingEntry(BaseModel):
    """The value of the setting `key`: `ids` for an entity or action list, `per_action` for an entity-per-action one
    (the other is empty). A setting with no entry is empty."""

    key: str = Field(max_length=64)
    ids: list[str] = Field(default=[], max_length=200)
    per_action: list[ActionIds] = Field(default=[], max_length=20)


class ConnectionSettings(BaseModel):
    """A connection's settings. `revision` counts the writes, 0 for a connection never set, and is what the next write
    must carry; `updated_at` and `updated_by` say who wrote them last (null for a connection never set, and `updated_by`
    null once the person is gone)."""

    connection_id: int
    kind: str
    revision: int
    settings: list[SettingInfo]
    values: list[SettingEntry]
    updated_at: datetime | None
    updated_by: Person | None


class ConnectionSettingsRequest(BaseModel):
    """The whole of a connection's settings, replacing what is stored, and the `revision` they were read at."""

    revision: int = Field(ge=0)
    values: list[SettingEntry] = Field(max_length=32)


class SettingsRefused(BaseModel):
    """Why settings were not stored; nothing was. `reason`: `unknown_key`, the kind has no such setting;
    `wrong_shape`, the value is not the setting's shape; `bad_id`, an id is not `domain.name` or an action is not one the
    setting takes; `too_many`, a list is too long. `key` is the setting it concerns."""

    key: str
    reason: Literal["unknown_key", "wrong_shape", "bad_id", "too_many"]
    detail: str


class SettingChange(BaseModel):
    """One key a write changed: the values themselves are not listed. `edited_by` is null once the person is gone."""

    id: int
    key: str
    edited_by: Person | None
    changed_at: datetime


class SettingChanges(BaseModel):
    """The changes, newest first. `next_before` is the `before` that fetches the page after, null at the end."""

    changes: list[SettingChange]
    next_before: int | None


class CatalogueEntityInfo(BaseModel):
    """A thing the service has: `entity_id` (`domain.object_id`), `name` to show, its `domain` and `device_class`."""

    entity_id: str
    name: str
    domain: str
    device_class: str | None


class CatalogueActionInfo(BaseModel):
    """An action the service offers (`domain.name`). `looks_up_only`: the service itself says it only returns data and
    changes nothing."""

    name: str
    domain: str
    looks_up_only: bool


class ConnectionCatalogue(BaseModel):
    """What the connection's service has now for a setting to pick from, read live at `read_at`, narrowed to `domains`
    when asked."""

    entities: list[CatalogueEntityInfo]
    actions: list[CatalogueActionInfo]
    read_at: datetime
