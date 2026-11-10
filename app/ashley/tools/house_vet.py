"""The view of a `house_do` call as the action judge sees it (`action_judge.View`), built from the things the call
resolves to in the house now: the action when the house offers an action of that name, and the household's own names of the
things it acts on, never the call's own words. `data`, the action's other fields, is shown as a size."""

from collections.abc import Mapping

from ..home_assistant.house import House, HouseUnavailable
from . import house_args as args
from .action_judge import View
from .house_targets import entity_of, named

DO = "house_do"
SHOWN_THINGS = 8


async def view_of(house: House, arguments: Mapping[str, object]) -> View:
    """The view of the call `arguments` make. A call whose arguments cannot be read, or while the house does not answer, is
    shown by sizes alone."""
    try:
        action = args.required(arguments, "action")
        states = tuple(await house.states())
        found = named(tuple(entity_of(s) for s in states), arguments, action.partition(".")[0])
        offered = {a.name for a in await house.actions()}
    except (ValueError, HouseUnavailable):
        return View(DO, {"action": "<unreadable>"})
    by_id = {s.id: s.name for s in states}
    things = [by_id[i] for i in found.ids]
    fields = {"action": action if action in offered else f"<text, {len(action)} chars>",
              "things": _things(things, found.unknown or bool(found.ambiguous))}
    data = arguments.get("data")
    if data is not None:
        fields["data"] = f"<text, {len(data)} chars>" if isinstance(data, str) else "<object>"
    return View(DO, fields)


def _things(names: list[str], unresolved: bool) -> str:
    if not names:
        return "none found in the house" if unresolved else "none named"
    shown = ", ".join(names[:SHOWN_THINGS])
    return shown if len(names) <= SHOWN_THINGS else f"{shown} and {len(names) - SHOWN_THINGS} more"
