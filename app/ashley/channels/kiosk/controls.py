"""A device's touch controls: each a button that turns one light of the house on, off or the other way round, or starts one of its scenes, carried out by code through the
device's household's tools as `house_do` with the entity's id, never by the model and never by a name matched loosely.
The list is the body of the device's screen's `controls` piece (`workshop.screen_controls`; until the device's screen
exists, its `DeviceControls` rows), edited by a person in the Devices room and by her, each light picked from the
house's catalogue; a household starts with none.

`id` is 1 to 40 of `[a-z0-9-]`, unique on the device and shown nowhere; `label` 1 to 40 characters, what the button
says; `action` one of `ACTIONS`' keys; `entity_id` a light or scene of the house's catalogue, in the action's domain. At most
`MAX_CONTROLS` per device.

Logs `kiosk.control` with the device id, the control id and the outcome (`ok` or `error`); never results, which can
name people and places."""

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from ... import logs
from ...inference.model import ToolCall
from ...tools.everyday import HouseholdTools
from ...tools.light_state import lights_on
from ...workshop.screen_controls import ACTIONS, ID, MAX_CONTROLS, Action, Control

__all__ = ["ACTIONS", "Action", "Control", "ControlRefused", "MAX_CONTROLS", "Reason", "Wanted", "lights_on", "run", "validate"]

Reason = Literal["too_many", "bad_label", "bad_id", "duplicate_id", "unknown_entity"]
log = logging.getLogger("ashley.channels.kiosk")


@dataclass(frozen=True)
class Wanted:
    """A control as a person asks for it: `id` None when it is new, and the entity not yet checked."""

    id: str | None
    label: str
    action: Action
    entity_id: str


class ControlRefused(Exception):
    """A list of controls that cannot be stored, for `reason`."""

    reason: Reason

    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason = reason


def validate(wanted: Iterable[Wanted], domains: Mapping[str, str]) -> tuple[Control, ...]:
    """The controls `wanted` asks for, in order, each given an id when it has none. `domains` maps every entity id of
    the house's catalogue to its domain. Raises ControlRefused."""
    asked = tuple(wanted)
    if len(asked) > MAX_CONTROLS:
        raise ControlRefused("too_many")
    given = [w.id for w in asked if w.id is not None]
    taken = set(given)
    if len(taken) != len(given):
        raise ControlRefused("duplicate_id")
    out: list[Control] = []
    for w in asked:
        label = w.label.strip()
        if not 1 <= len(label) <= 40:
            raise ControlRefused("bad_label")
        if w.id is not None and not ID.fullmatch(w.id):
            raise ControlRefused("bad_id")
        if domains.get(w.entity_id) != w.action.split(".")[0]:
            raise ControlRefused("unknown_entity")
        ident = w.id if w.id is not None else _fresh(label, taken)
        taken.add(ident)
        out.append(Control(ident, label, w.action, w.entity_id))
    return tuple(out)


def _fresh(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:36].strip("-") or "control"
    ident, n = base, 1
    while ident in taken:
        n += 1
        ident = f"{base}-{n}"
    return ident


async def run(control: Control, device_id: int, household_id: int) -> bool:
    """Run the control through the device's household's everyday tools; whether the house reported success. Never
    raises for the tool's failure."""
    call = ToolCall(f"kiosk-{control.id}", "house_do", {"action": control.action, "ids": [control.entity_id]})
    result = await HouseholdTools(household_id).call(call)
    logs.info(log, "kiosk.control", device=device_id, control=control.id, outcome="error" if result.is_error else "ok")
    return not result.is_error
