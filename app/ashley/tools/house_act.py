"""`house_do` and `house_ask`: run an action in the house. `house_ask` is for an action that only reads (one that returns
data and changes nothing: a calendar's events, a list's items, a script listed as a read in `home_assistant.json`);
`house_do` for any other, whose result says which things changed and to what. The things are named by `ids`, or by
`area`, `domain` and `name` as `house_state` matches them, resolved here from the house's own names and aliases; a name
that fits several things, none of them named exactly that, acts on none and says which fit. An action that
`irreversible.json` names is not run: the person is asked first (`house_change`).

The `tools.call` line carries the tool, the action, the outcome and how many things it named and changed."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from .. import logs, services
from ..home_assistant.house import House, HouseRejected, Performed
from ..home_assistant.house_values import HouseValues
from ..home_assistant.irreversible import Irreversible
from ..inference.model import ToolSpec
from ..senses.outside_record import OutsideRecord, OutsideRecordUnavailable
from . import house_args as args, tainted
from .excluding import is_excluded
from .house_answer import Answer, error, fit
from .house_look_config import HouseLookConfig
from .house_targets import entity_of, named

log = logging.getLogger("ashley.tools")
DO = "house_do"
ASK = "house_ask"
_PARAMETERS = {"type": "object", "properties": {
    "action": {"type": "string", "description": "The action, domain.name (light.turn_on, climate.set_temperature, "
                                                "calendar.get_events); house_find kind action lists them with their fields."},
    "ids": {"type": "array", "items": {"type": "string"}, "description": "Exact ids of the things, as an answer showed them."},
    "name": {"type": "string", "description": "Words from the thing's name or an alias, e.g. porch light."},
    "area": {"type": "string", "description": "An area's name or alias: acts on every matching thing in it."},
    "domain": {"type": "string", "description": "Narrows to one domain; the action's own domain is assumed."},
    "data": {"type": "string", "description": "The action's other fields as a JSON object in text: "
                                              "{\"brightness_pct\": 30} for light.turn_on, {\"item\": \"milk\"} for "
                                              "todo.add_item, {\"temperature\": <degrees, in the household's units>} for "
                                              "climate.set_temperature; "
                                              "house_find kind action gives an action's fields."}},
    "required": ["action"]}
DO_SPEC = ToolSpec(DO, (
    "Do something in the house: run any action on the things you name (turn a light on or off or dim it, set the "
    "thermostat, lock or unlock, start a script, add to a list). Name the things by name, area and domain as they were "
    "shown to you; the answer says which things changed and to what. A name that fits several things acts on none and "
    "says which fit. Some actions need the person's OK and are not run."), _PARAMETERS, outside=False, tier="judged", label="Changed something in the house")
ASK_SPEC = ToolSpec(ASK, (
    "Ask the house for data with an action that changes nothing: a calendar's events (calendar.get_events), a list's "
    "items (todo.get_items), a weather forecast, a script that only looks something up. The things are named as for "
    "house_do. An action that changes things is refused here."), _PARAMETERS, reads=True, outside=True)
_ARGUMENTS = ("action", "ids", "name", "area", "domain", "data")


@dataclass(frozen=True)
class Rules:
    """`excluded`: actions she is never offered. `reads`: actions that change nothing though the house does not say.
    `irreversible`: which operations need the person's OK first. `household_reads`: for a read, the entities whose
    response the household alone writes; a read does not taint the turn when it named entities and every one is listed
    for its action, and any other read does.
    `service_reads`: the reads whose response a service the household trusts writes, whatever they name. The shipped
    rules hold `excluded` and `irreversible` alone; the rest are the household's own settings, empty until
    `for_household` applies them."""

    excluded: tuple[str, ...]
    reads: tuple[str, ...]
    irreversible: Irreversible
    household_reads: Mapping[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    service_reads: tuple[str, ...] = ()

    def for_household(self, values: HouseValues) -> "Rules":
        """These rules with the household's settings: its `reads`, `household_reads` and `service_reads`."""
        return replace(self, reads=values.reads, household_reads=values.household_reads,
                       service_reads=values.service_reads)


async def run(house: House, tool: str, arguments: Mapping[str, object], rules: Rules, config: HouseLookConfig,
              household_id: int = 0) -> Answer:
    args.only(arguments, tool, _ARGUMENTS)
    action = args.required(arguments, "action")
    domain_of_action, _, short = action.partition(".")
    if not domain_of_action or not short or is_excluded(action, rules.excluded):
        return error(f"no action named {action}", action=action)
    if tool == ASK and not await _only_reads(house, action, rules):
        return error(f"{action} changes things; house_do runs it", action=action)
    if tool == DO and rules.irreversible.covers(f"perform:{action}"):
        return error(f"{action} needs the person's OK first and was not run: tell them what it would do and ask", action=action)
    states = tuple(entity_of(s) for s in await house.states())
    found = named(states, arguments, domain_of_action)
    if found.ambiguous:
        return error(f"that fits several: {', '.join(found.ambiguous)}; nothing was done, say which", action=action,
                     named=len(found.ambiguous))
    if found.unknown:
        return error("nothing in the house matches that; there is no such thing, so say so instead of asking again",
                     action=action, named=0)
    try:
        done = await house.perform(action, found.ids, args.mapping(arguments, "data"))
    except HouseRejected as e:
        return error(f"the house refused it: {e.message}", action=action, named=len(found.ids))
    answer = _answer(action, found.ids, done, {e.id: e.names[0] for e in states}, config)
    if tool == DO:
        await _noted(household_id, action, found.ids)
    return replace(answer, outside=False) if tool == ASK and await _untainted(action, found.ids, rules, household_id) else answer


async def _untainted(action: str, named: tuple[str, ...], rules: Rules, household_id: int) -> bool:
    """Whether a read's response is the household's or a trusted service's alone: a list only the household fills, unless
    a tainted turn has written it within `writes_keep_s`. A record that cannot be read leaves it outside."""
    if action in rules.service_reads:
        return True
    allowed = rules.household_reads.get(action, ())
    if not named or not all(i in allowed for i in named):
        return False
    try:
        return not await services.get(OutsideRecord).written(household_id, named)
    except OutsideRecordUnavailable:
        return False


async def _noted(household_id: int, action: str, named: tuple[str, ...]) -> None:
    """A list a tainted turn wrote is noted, so a read of it is outside for a while (`OutsideRecord.wrote`)."""
    if tainted.current() is None or not action.startswith("todo."):
        return
    try:
        for entity in named:
            await services.get(OutsideRecord).wrote(household_id, entity, datetime.now(UTC))
    except OutsideRecordUnavailable:
        logs.warning(log, "outside.unrecorded", tool=DO, where="writes")


async def _only_reads(house: House, action: str, rules: Rules) -> bool:
    if is_excluded(action, rules.reads):
        return True
    return any(a.name == action and a.response == "only" for a in await house.actions())


def _answer(action: str, named: tuple[str, ...], done: Performed, names: Mapping[str, str],
            config: HouseLookConfig) -> Answer:
    changed = [{"id": s.id, "name": s.name, "state": s.state} for s in done.changed if s.id in named or not named]
    moved = {c["id"] for c in changed}
    body = {"done": True, "action": action, "changed": changed,
            **({"unchanged": [names.get(i, i) for i in named if i not in moved]} if named and len(moved) < len(named) else {}),
            **({} if done.response is None else {"response": done.response})}
    text, form = fit([body, {**body, "response": f"too long to show ({len(str(done.response))} characters)"}],
                     config.max_chars)
    return Answer(text, False, {"action": action, "named": len(named), "changed": len(changed),
                                "form": form})
