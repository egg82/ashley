"""Handing a connection to the household and taking it back (`PostgresConnections.move`): one transaction that checks
the move is allowed, seals the secret and the access token again bound to the new holder (a sealed value is bound to
household, kind and person, so one moved without it would not open), raises `secret_version` so a refresh that read
the old row cannot write over it, and sets every resource shared (to the household) or kept (back to a person)."""

from typing import Any

from ..db.database import Database
from . import queries
from .connections import ConnectionsUnavailable, LabelTaken, NotAdder, TooMany
from .kinds import ConnectionKinds
from .model import Connection, Holder
from .rows import connection_of, translated
from .sealing import Sealer, Unsealable, bound_to
from .. import services

LOCKED = f"SELECT {queries.COLUMNS}, secret, access_token FROM connections WHERE id = %(id)s AND {queries.VISIBLE} FOR UPDATE"
LABEL_USED = ("SELECT EXISTS (SELECT 1 FROM connections WHERE household_id = %(household)s AND kind = %(kind)s "
              "AND label = %(label)s AND person_id IS NOT DISTINCT FROM %(owner)s::bigint AND id <> %(id)s)")
HELD = ("SELECT count(*) FROM connections WHERE household_id = %(household)s AND kind = %(kind)s "
        "AND person_id IS NOT DISTINCT FROM %(owner)s::bigint")
MOVE = (f"UPDATE connections SET person_id = %(owner)s::bigint, secret = %(secret)s, access_token = %(access)s::bytea, "
        f"secret_version = secret_version + 1 WHERE id = %(id)s RETURNING {queries.COLUMNS}")
FLAG = "UPDATE connection_resources SET shared = %(shared)s WHERE connection_id = %(id)s"


def _resealed(sealer: Sealer, row: tuple[Any, ...], old: bytes, new: bytes) -> tuple[bytes, bytes | None]:
    try:
        secret = sealer.seal(sealer.open(bytes(row[11]), old), new)
        access = None if row[12] is None else sealer.seal(sealer.open(bytes(row[12]), old), new)
    except Unsealable as e:
        raise ConnectionsUnavailable("the stored secret does not open under this key") from e
    return secret, access


async def move(database: Database, sealer: Sealer, connection_id: int, household_id: int, person_id: int,
               holder: Holder) -> Connection | None:
    """The connection now held by `holder`; None when it is not visible to `person_id`. Raises ValueError for a holder
    its kind does not allow, NotAdder for taking back one `person_id` did not hand over, LabelTaken and TooMany when the
    new holder has one under that label or as many as the kind allows, ConnectionsUnavailable. Nothing is written for
    any of them."""
    args: dict[str, Any] = {"id": connection_id, "household": household_id, "person": person_id}
    with translated():
        async with database.connection() as conn:
            row = await (await conn.execute(LOCKED, args)).fetchone()
            if row is None:
                return None
            connection = connection_of(row)
            kind = services.get(ConnectionKinds).get(connection.kind)
            if kind is None or holder not in kind.holders:
                raise ValueError("that kind cannot be held that way")
            if (connection.person_id is None) == (holder == "household"):
                return connection
            if holder == "person" and connection.added_by != person_id:
                raise NotAdder
            owner = person_id if holder == "person" else None
            args |= {"kind": kind.name, "owner": owner, "label": connection.label}
            await conn.execute(queries.LOCK, {"owner": f"{household_id}/{kind.name}/{owner}"})
            if (await (await conn.execute(LABEL_USED, args)).fetchone() or (False,))[0]:
                raise LabelTaken(kind.name)
            if (await (await conn.execute(HELD, args)).fetchone() or (0,))[0] >= kind.most:
                raise TooMany(kind.name)
            secret, access = _resealed(sealer, row, bound_to(household_id, kind.name, connection.person_id),
                                       bound_to(household_id, kind.name, owner))
            moved = await (await conn.execute(MOVE, {**args, "secret": secret, "access": access})).fetchone()
            await conn.execute(FLAG, {**args, "shared": holder == "household"})
    return None if moved is None else connection_of(moved)
