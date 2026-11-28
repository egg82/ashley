"""The controls of a person's house routes (`ashley.api.house`): the lights and scenes of the household's catalogue, each
as the kiosk's `Control`, so a press is carried out as a kiosk's is (`controls.run`) and `ACTIONS` alone says what may be
done. Nothing is stored: the list is the catalogue now, and a control's id is its entity's (`light.hall_lamp` is
`light-hall-lamp`), stable while the entity is.

An entity whose id does not fit `[a-z0-9-]{1,40}` as a control id, or whose id a second entity shares once written so, is
left out: a name must mean one thing. A label is the entity's name cut to 40 characters, or its own id when it has none."""

from ...connections.model import CatalogueEntity
from ...workshop.screen_controls import ACTIONS, ID, Action, Control
from .house_domains import entities

_ACTION_OF: dict[str, Action] = {"light": ACTIONS["light.toggle"], "scene": ACTIONS["scene.turn_on"]}


def of_entities(found: list[CatalogueEntity]) -> tuple[Control, ...]:
    """The controls for the lights and scenes among `found`, ordered by entity id."""
    made: dict[str, Control] = {}
    clashing: set[str] = set()
    for e in sorted(found, key=lambda e: e.id):
        action = _ACTION_OF.get(e.domain)
        ident = e.id.replace(".", "-").replace("_", "-")
        if action is None or not e.id.startswith(f"{e.domain}.") or not ID.fullmatch(ident):
            continue
        if ident in made:
            clashing.add(ident)
        label = e.name.strip()[:40].strip() or e.id
        made[ident] = Control(ident, label, action, e.id)
    return tuple(c for i, c in made.items() if i not in clashing)


async def listed(household_id: int, person_id: int) -> tuple[Control, ...]:
    """The household's lights and scenes as controls, read now. Raises ConnectionsUnavailable, CatalogueUnavailable."""
    return of_entities(await entities(household_id, person_id))
