"""The wire shapes of a device's touch controls, as the Devices room reads and replaces them."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from ..channels.kiosk.controls import Action

Refusal = Literal["too_many", "bad_label", "bad_id", "duplicate_id", "unknown_entity", "full", "already_shown", "required"]
EntityId = Annotated[str, StringConstraints(pattern=r"^[a-z_]+\.[a-z0-9_]+$", max_length=255)]
Label = Annotated[str, StringConstraints(max_length=200)]


class DeviceControl(BaseModel):
    """One control as stored: `name` its stable key on the device, `label` what its button says, `entity_id` the light or
    scene the house calls it, which `action` turns on, off or toggles (a scene only on)."""

    name: str
    label: str
    action: Action
    entity_id: str


class DeviceControlList(BaseModel):
    """A device's touch controls in the order its screen shows them; empty when it has none. `piece_version` is the controls
    piece's version, which an edit names as `base_version`: 0 while the screen has no controls piece or has not been laid
    out."""

    device_controls: list[DeviceControl]
    piece_version: int


class DeviceControlWanted(BaseModel):
    """One control asked for: `name` is the key of a control already on the device, null for a new one, which is given a
    key from its label."""

    name: str | None = None
    label: Label
    action: Action
    entity_id: EntityId


class DeviceControlsRequest(BaseModel):
    """The whole list a device is to show: it replaces what it had, if the list is still at `base_version`, the `piece_version`
    last read."""

    wanted: list[DeviceControlWanted]
    base_version: int = Field(ge=0)


class ControlsRefused(BaseModel):
    """Why the controls were not stored; nothing was. `reason`: `too_many`; `bad_label`, a label of 1 to 40
    characters is wanted; `bad_id`, a name outside `[a-z0-9-]{1,40}`; `duplicate_id`, a name is used twice;
    `unknown_entity`, a light the house's catalogue does not have, or one the action does not suit; `full`, the screen
    holds as many pieces as it can; `already_shown`, `required`, which a screen's layout rules refuse."""

    reason: Refusal
    detail: str
