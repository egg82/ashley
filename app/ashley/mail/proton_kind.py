"""Proton as a connection kind: a person's own Proton account, logged in once from the room through Bridge
(`ashley.api.mail_bridge_login`). Its sealed secret is the password Bridge issued for the account, with which the IMAP
adapter signs in; the address is fixed, since every account is reached through the one Bridge. Registered only where Bridge is
wired (`ashley.wiring_bridge`), so no Proton kind is offered where nothing could connect it."""

from .. import services
from ..connections.kinds import BridgeLogin, ConnectionKind, Refusal, ResourcesUnavailable
from ..connections.model import Listed, Opened
from .proton_bridge import BridgeUnavailable, ProtonBridge

NAME = "proton"
ADDRESS = "bridge://proton"


async def _check(base: str, secret: str, person_id: int) -> Refusal | None:
    try:
        await services.get(ProtonBridge).holder()
    except BridgeUnavailable:
        return "unreachable"
    return None


async def _mailboxes(opened: Opened) -> tuple[Listed, ...]:
    """One mailbox per address of the Bridge account the connection is. Raises ResourcesUnavailable."""
    try:
        accounts = await services.get(ProtonBridge).accounts()
    except BridgeUnavailable:
        raise ResourcesUnavailable("bridge_unavailable") from None
    held = next((a for a in accounts if a.connection_id == opened.connection.id), None)
    if held is None:
        raise ResourcesUnavailable("not_held")
    return tuple(Listed(a, "mailbox", a) for a in held.addresses)


PROTON = ConnectionKind(
    name=NAME, title="Proton Mail", what="your Proton mail",
    blurb="Log in to your Proton account once, here, so she can read your Proton mail. Your password and code go to "
          "Proton Mail Bridge and are not kept.",
    connected="Connected. Proton Mail Bridge holds your account.",
    removed="Removed. She can’t reach your Proton mail now.",
    holders=frozenset({"person"}), schemes=frozenset(), address_placeholder="", fixed_address=ADDRESS, secret_field="token",
    secret_label="", secret_noun="", check=_check, ports=frozenset({"mail"}), most=5,
    refusals={"bad_url": "Proton’s address is fixed", "key_refused": "Bridge no longer holds this account; log in again",
              "unreachable": "Proton Mail Bridge is not running right now",
              "wrong_service": "what answered is not Proton Mail Bridge"},
    connect=BridgeLogin(), resources=_mailboxes)
