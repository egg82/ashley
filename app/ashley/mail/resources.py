"""A mail connection's resources: one mailbox per account the provider gives, named by its address
(`ConnectionKind.resources`). Gmail's account is one mailbox."""

from .. import services
from ..connections.kinds import ResourcesUnavailable
from ..connections.model import Listed, Opened
from .mailbox import Mailbox
from .model import Account, MailFailed


async def mailboxes(opened: Opened) -> tuple[Listed, ...]:
    """Raises ResourcesUnavailable."""
    connection = opened.connection
    try:
        address = await services.get(Mailbox).address(Account(connection.id, connection.household_id, connection.person_id))
    except MailFailed as e:
        raise ResourcesUnavailable(e.reason) from None
    return (Listed(address, "mailbox", address),)
