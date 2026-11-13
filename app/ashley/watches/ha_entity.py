"""The `ha_entity` kind: one thing in the household's Home Assistant, by its entity id. Its states come from
`ashley.home_assistant.held_states.HeldStates`, which the job holds through `hold`: a subscription per thing over one
socket per household, so a check is a read of what the house last told and costs the house nothing, and a change
nudges a check at once. An item is keyed by the entity id and tracks `state`. A thing the house does not have reads
as no items, which is gone."""

import re
from collections.abc import Callable, Mapping, Sequence

from .. import services
from ..criteria.record import Change
from ..home_assistant.held_states import EntityState, HeldStates
from ..home_assistant.homes import Homes, HomesUnavailable
from ..home_assistant.house import HouseUnavailable
from .config import CONFIG
from .diff import Items, to_items
from .kinds import Kind
from .model import Read, ReadFailed, Watch

NAME = "ha_entity"
ENTITY_ID = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
NOTE = ("A thing in the house you keep watch on changed state; the message says from what to what. Tell the person "
        "only if they would want to know.")


class HaEntity(Kind):
    name = NAME

    async def hold(self, nudge: Callable[[], None]) -> None:
        await services.get(HeldStates).hold(nudge)

    async def read(self, group: Sequence[Watch]) -> Mapping[int, Read]:
        first = group[0]
        wanted = [w.target for w in group if ENTITY_ID.fullmatch(w.target)]
        found: Mapping[str, EntityState | None] | None = {}
        try:
            if wanted:
                found = await services.get(HeldStates).states(first.household_id, wanted)
        except (HouseUnavailable, HomesUnavailable):
            return {w.id: ReadFailed("unreachable") for w in group}
        if found is None:
            return {w.id: ReadFailed("not_connected") for w in group}
        return {w.id: items_of(w.target, found.get(w.target)) for w in group}

    def said(self, watch: Watch, changes: Sequence[Change]) -> str:
        last = changes[-1] if changes else None
        if last is None or last.after is None:
            return f"{watch.label}: no longer in the house"
        before = "" if last.before is None else f"{last.before.get('state')} to "
        return f"{watch.label}: {before}{last.after.get('state')}"

    def note(self, watch: Watch, changes: Sequence[Change]) -> str:
        return NOTE

    async def available(self, household_id: int, person_id: int) -> bool:
        try:
            return await services.get(Homes).of(household_id) is not None
        except HomesUnavailable:
            return False

    async def label(self, watch: Watch) -> str:
        if not ENTITY_ID.fullmatch(watch.target):
            return watch.target
        try:
            found = await services.get(HeldStates).states(watch.household_id, [watch.target])
        except (HouseUnavailable, HomesUnavailable):
            return watch.target
        state = None if found is None else found.get(watch.target)
        return watch.target if state is None else state.name


def items_of(entity_id: str, state: EntityState | None) -> Items:
    """What the thing reads as: its tracked fields, or no items when the house does not have it."""
    if state is None:
        return {}
    return to_items({entity_id: {f: {"state": state.state}[f] for f in CONFIG.kinds[NAME].track}}, CONFIG.max_value_chars)
