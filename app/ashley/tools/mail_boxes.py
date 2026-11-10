"""The rows of `mail_boxes`: every mailbox the speaker may see, each saying by `unavailable` why her mail tools cannot
use it now, or carrying no such field when they can. Logs `mail.boxes` with the listed count and a count per reason,
never an address."""

import logging
from collections import Counter
from typing import Literal, get_args

from .. import logs
from ..connections.model import Connection
from ..connections.resources import Usable
from ..mail.mailbox import Mailbox
from ..mail.model import Account

log = logging.getLogger("ashley.tools")
Unavailable = Literal["needs_reconnect", "signed_out", "missing_scope", "not_supported", "not_shared"]
REASONS = get_args(Unavailable)
DESCRIPTION = ("List the mailboxes this turn may see. A row with `unavailable` cannot be read or changed now: "
               "needs_reconnect (its connection expired or was revoked), signed_out (its login must be done again), "
               "missing_scope (it was not granted the right to read), not_supported (no reader exists for its kind), "
               "not_shared (its owner kept it, so it has no address here). `syncing` means a read says it is still "
               "being filled in.")


def reason(mailbox: Mailbox, connection: Connection) -> Unavailable | None:
    """Why a connection that this turn may use cannot be read now; None when it can."""
    if not mailbox.supports(connection.kind):
        return "not_supported"
    if not mailbox.can_read(connection.kind, connection.scopes):
        return "missing_scope"
    if connection.needs is not None:
        return "needs_reconnect" if connection.needs == "reconnect" else "signed_out"
    return None


async def row(mailbox: Mailbox, use: Usable) -> dict[str, object]:
    why = reason(mailbox, use.connection)
    syncing = why is None and await mailbox.still_syncing(
        Account(use.connection.id, use.connection.household_id, use.opens_for, use.connection.kind, use.resource.ref))
    found: dict[str, object] = {"address": use.resource.ref, "shared": use.resource.shared, "syncing": syncing}
    return found if why is None else found | {"unavailable": why}


def kept(count: int) -> list[dict[str, object]]:
    """A row for each of `count` mailboxes the speaker may see but not use on this turn, naming nothing of them."""
    return [{"shared": False, "unavailable": "not_shared"} for _ in range(count)]


def logged(rows: list[dict[str, object]]) -> None:
    counts = Counter(r["unavailable"] for r in rows if "unavailable" in r)
    logs.info(log, "mail.boxes", listed=len(rows), **{k: counts.get(k, 0) for k in REASONS})
