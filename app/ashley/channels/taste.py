"""The household's persona overrides for one prompt (`ashley.skills.persona`), read fresh for every reply and errand."""

import logging
from collections.abc import Mapping

from .. import logs, services
from ..skills.persona import PersonaOverrides, PersonaUnavailable, bodies

log = logging.getLogger("ashley.channels")


async def overrides(household_id: int) -> Mapping[str, str]:
    """The household's override of each persona section it changed (`persona.Context.overrides`); none, so the shipped
    persona, when they cannot be read, which logs `persona.overrides_unreachable`."""
    try:
        found = bodies(await services.get(PersonaOverrides).heads(household_id))
    except PersonaUnavailable:
        logs.info(log, "persona.overrides_unreachable", household=household_id)
        return {}
    if found:
        logs.info(log, "persona.overrides_applied", household=household_id, sections=len(found))
    return found
