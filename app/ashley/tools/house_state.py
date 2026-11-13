"""`house_state`, the house's live state read in code: one tool with structured arguments that narrow it like a map
(the house, an area, the entities), answered from the house (`house.House.states`): the things the household lists for
her by name, or with `all` everything in it. Read afresh for each call and summarised in code (`house_render`), with no
model step.

The `tools.call` line carries the outcome, the level, how many children it had, whether it was answered in counts,
and the duration; never an argument, a name or a state."""

import logging
import time

from .. import logs
from ..home_assistant.house import House, HouseUnavailable
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..people.zone import zone_of
from .house_entities import NO_AREA
from .house_query import query_of
from .house_render import answer
from .house_state_config import HouseStateConfig
from .house_targets import entity_of

log = logging.getLogger("ashley.tools")

NAME = "house_state"
DESCRIPTION = (
    "The house's live state, read now: what is on or off, open or locked, who is home, temperatures and other "
    "readings, for the devices you were given. This is the tool for retrieving live context. all true includes every "
    "other thing the house has (helpers, diagnostics, devices not listed for you), which house_find also looks up. Its arguments "
    "narrow it like a map: none gives every area with a one-line summary by domain; area alone gives every domain in "
    "that area; domain (with or without area), or name, gives the devices themselves with their states and, when known, changed: when the state last changed. Use area and "
    "domain values exactly as an answer shows them. Every list in an answer is the whole list: when the full answer "
    "would be too long it shows less of each (names without states, or counts), complete is false and narrow_by "
    "names the arguments to add. "
    "matched 0 is final: nothing you can see matches, and for a name the answer shows the whole house beside it, so "
    "say what there is; do not ask again in other words.")
PARAMETERS = {"type": "object", "properties": {
    "area": {"type": "string", "description": f"An area as an answer names it, e.g. Kitchen; {NO_AREA} "
                                              "for devices in none."},
    "domain": {"type": "string", "description": "A domain as an answer names it: light, climate, sensor, media_player."},
    "name": {"type": "string", "description": "Words from a device's name, e.g. porch light; every word must match "
                                              "its name, an alias, its area, its domain or its kind (battery, temperature)."},
    "all": {"type": "boolean", "description": "Include everything the house has, not only the devices you were given."}}}
SPEC = ToolSpec(NAME, DESCRIPTION, PARAMETERS, reads=True, outside=False)


class HouseStateTools:
    """`house_state` over a House. `call` never raises."""

    def __init__(self, house: House, config: HouseStateConfig, household_id: int = 0) -> None:
        self._house = house
        self._config = config
        self._household_id = household_id

    async def call(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        try:
            wanted = call.arguments.get("all", False)
            if not isinstance(wanted, bool):
                raise ValueError("house_state's all is true or false")
            query = query_of({k: v for k, v in call.arguments.items() if k != "all"})
        except ValueError as e:
            return _done(call, "error", started, ToolResult(call.id, str(e), True))
        try:
            states = await self._house.states()
        except HouseUnavailable:
            return _done(call, "unavailable", started, ToolResult(call.id, "the house did not answer", True))
        entities = tuple(entity_of(s) for s in states if wanted or s.featured)
        got = answer(entities, query, self._config, await zone_of(self._household_id))
        logs.info(log, "tools.call", tool=NAME, outcome="ok", level=got.level, children=got.children,
                  capped=got.capped, everything=wanted, chars=len(got.text), duration_ms=_ms(started))
        return ToolResult(call.id, got.text, outside=got.outside)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _done(call: ToolCall, outcome: str, started: float, result: ToolResult, **fields: str) -> ToolResult:
    logs.info(log, "tools.call", tool=call.name, outcome=outcome, **fields, duration_ms=_ms(started))
    return result
