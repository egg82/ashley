"""The kind-keyed way suites address a connection (one per household and kind, or per person and kind), over the
id-keyed `Connections`: look the connection up by kind and owner, then call by its id."""

from ashley import services
from ashley.connections.connections import Connections
from ashley.connections.kinds import ConnectionKinds
from ashley.connections.model import Connection, Kind, Opened


async def find_of(connections: Connections, household_id: int, kind: Kind, person_id: int | None = None
                  ) -> Connection | None:
    """The connection of `kind` owned by the household (`person_id` None) or by that person."""
    found = await connections.of_household(household_id, person_id)
    return next((c for c in found if c.kind == kind and c.person_id == person_id), None)


async def opened_of(connections: Connections, household_id: int, kind: Kind,
                    person_id: int | None = None) -> Opened | None:
    held = await find_of(connections, household_id, kind, person_id)
    return None if held is None else await connections.opened(held.id, household_id, person_id)


async def remove_of(connections: Connections, household_id: int, kind: Kind, person_id: int | None = None) -> bool:
    held = await find_of(connections, household_id, kind, person_id)
    return held is not None and await connections.remove(held.id, household_id, person_id)


async def put_of(connections: Connections, household_id: int, kind: Kind, base_url: str, secret: str,
                 added_by: int) -> Connection:
    """Add the connection, or replace the one the owner already holds of that kind."""
    owner = added_by if services.get(ConnectionKinds).is_personal(kind) else None
    held = await find_of(connections, household_id, kind, owner)
    if held is None:
        return await connections.add(household_id, kind, "", base_url, secret, added_by)
    replaced = await connections.replace(held.id, household_id, added_by, base_url, secret)
    assert replaced is not None
    return replaced
