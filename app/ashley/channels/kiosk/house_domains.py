"""The entities of the house's catalogue a touch control may name, with their domains."""

from ... import services
from ...connections.connections import Connections
from ...connections.kinds import ConnectionKinds


async def domains(household_id: int, person_id: int) -> dict[str, str]:
    """Each entity id of the catalogues of the household's own connections, with its domain. Raises
    ConnectionsUnavailable, CatalogueUnavailable."""
    out: dict[str, str] = {}
    for held in await services.get(Connections).of_household(household_id, person_id):
        kind = services.get(ConnectionKinds).get(held.kind)
        if held.person_id is not None or kind is None or kind.catalogue is None:
            continue
        opened = await services.get(Connections).opened(held.id, household_id, person_id)
        if opened is not None:
            out.update({e.id: e.domain for e in (await kind.catalogue(opened)).entities})
    return out
