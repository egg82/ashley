"""The tier of a `house_do` call (`tiers.of_house_do`), from the things it resolves to in the house as they are now: a
`switch` is a lamp or a garage relay by its `device_class`, and the household's `consequential_entities` (its
settings, read once per turn) are always judged. A call whose arguments cannot be read, or while the house does not answer, is judged: it would do nothing, and
judged is what an unclassified call is."""

from collections.abc import Mapping

from ..home_assistant.house import House, HouseUnavailable
from ..inference.model import Tier
from . import house_args as args
from .house_targets import entity_of, named
from .tiers import CONFIG, Target, of_house_do
from .tiers_config import TiersConfig


async def of_call(house: House, arguments: Mapping[str, object], config: TiersConfig = CONFIG,
                  consequential: tuple[str, ...] = ()) -> Tier:
    try:
        action = args.required(arguments, "action")
        states = tuple(await house.states())
        found = named(tuple(entity_of(s) for s in states), arguments, action.partition(".")[0])
    except (ValueError, HouseUnavailable):
        return "judged"
    by_id = {s.id: s for s in states}
    targets = tuple(Target(i, by_id[i].domain, _device_class(by_id[i].attributes)) for i in found.ids)
    return of_house_do(action, targets, config, consequential)


def _device_class(attributes: Mapping[str, object]) -> str | None:
    value = attributes.get("device_class")
    return value if isinstance(value, str) else None
