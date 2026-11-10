"""The kinds of connection (Type Object): what a service must declare to be connected. Each adapter declares its
`ConnectionKind` beside itself and `ashley.wiring` registers them; the routes, the stored rows and the panel read the
`ConnectionKinds` service, and nothing else lists kinds."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from ..services import Service
from . import address
from .model import Catalogued, Holder, Listed, Opened, Port
from .settings import Setting

FIRST_HOUSEHOLD = 1
"""The deployment's first household: the one its own setup (the env) describes, and the only one that holds a
`deployment` kind."""


@dataclass(frozen=True)
class Pasted:
    """Connected by a person pasting an address and a secret (Sure, Home Assistant, a code host, herdr)."""


@dataclass(frozen=True)
class OAuth:
    """Connected through `provider`'s OAuth consent screen (`ashley.connections.oauth.OAuthProvider`, registered under
    this name), asking for `scopes`. The kind's sealed secret is then the refresh token."""

    provider: str
    scopes: tuple[str, ...]

    def missing(self, granted: tuple[str, ...]) -> list[str]:
        """The asked-for scopes `granted` lacks. A provider may report a short scope as its URL (Google answers
        `email` with `https://www.googleapis.com/auth/userinfo.email`), so scopes are compared by their last segment."""
        have = {g.rsplit("/", 1)[-1].removeprefix("userinfo.") for g in granted}
        return [s for s in self.scopes if s.rsplit("/", 1)[-1].removeprefix("userinfo.") not in have]


@dataclass(frozen=True)
class BridgeLogin:
    """Connected by a person logging in to the service's own account from the room, once, through a program the app runs
    for it (Proton, through Bridge: `ashley.api.mail_bridge_login`). The kind's sealed secret is the password the
    service issued for the connection, never the one typed."""


Connect = Pasted | OAuth | BridgeLogin


class CatalogueUnavailable(Exception):
    """The service could not say what it has now (it did not answer, or turned the connection away)."""


class ResourcesUnavailable(Exception):
    """The service could not say what a connection reaches now (it did not answer, or turned the connection away). The
    resources stored stay as they were."""


Resources = Callable[[Opened], Awaitable[tuple[Listed, ...]]]
"""What a connection reaches, as its service names it, read with the connection opened. Raises ResourcesUnavailable."""

Catalogue = Callable[[Opened], Awaitable[Catalogued]]
"""What a service has that a person picks from in the connection's settings, read with the connection opened. Raises
CatalogueUnavailable."""

Refusal = Literal["bad_url", "key_refused", "unreachable", "wrong_service"]
Check = Callable[[str, str, int], Awaitable[Refusal | None]]
"""The one authenticated read against the service, given the address, the secret and the id of the person connecting
it: None when it answered for them, else why not."""


@dataclass(frozen=True)
class ConnectionKind:
    """One service a household or person can connect.

    `name` is the wire and stored name; `title` and `what` label it ("Sure", "finances"); `blurb` is what the panel
    says before it is connected, `connected` and `removed` what it says after. `holders` are who may hold a
    connection of the kind: the household, a person, or either (`default_holder` when a connection is made without
    saying). A kind takes an address a person types, limited to `schemes`, unless `fixed_address`
    is set (GitHub's API); a `pinned` kind's address ends in the fingerprint of its certificate (`address.base_url`).
    The secret is sent as `secret_field` and labelled `secret_label`, `secret_noun` being its
    name in a button ("key", "token"). `refusals` is the text for a person of each reason `check` or the address rule
    can give. `ports` are the ports it implements; `most` is how many connections of it one owner may hold. `connect`
    is how a person connects it: an OAuth kind's `check` reads the account with the new access token, and it has no
    address a person types, so it sets `fixed_address`. `resources` lists what a connection reaches; a kind with none
    reaches the whole service, whoever holds it. `settings` is what a person sets on a connection of the kind
    (`ashley.connections.settings`), none for a kind with nothing to set; `catalogue` lists what the service has for
    the settings to pick from. A `deployment` kind configures the whole deployment rather than one household (a model
    provider's key, which pays for every household's calls), so only `FIRST_HOUSEHOLD` holds it: it is offered to no
    other household and no other can add one (`ConnectionKinds.offered`)."""

    name: str
    title: str
    what: str
    blurb: str
    connected: str
    removed: str
    holders: frozenset[Holder]
    schemes: frozenset[str]
    address_placeholder: str
    secret_field: Literal["api_key", "token"]
    secret_label: str
    secret_noun: str
    check: Check
    refusals: Mapping[Refusal, str]
    ports: frozenset[Port]
    fixed_address: str | None = None
    pinned: bool = False
    most: int = 1
    connect: Connect = Pasted()
    resources: Resources | None = None
    settings: tuple[Setting, ...] = ()
    catalogue: Catalogue | None = None
    deployment: bool = False

    def __post_init__(self) -> None:
        if self.most < 1:
            raise ValueError("a kind allows at least one connection")
        if not self.holders:
            raise ValueError("a kind has at least one holder")

    @property
    def default_holder(self) -> Holder:
        """A person when the kind may be held by one, else the household."""
        return "person" if "person" in self.holders else "household"

    def base_url(self, typed: str | None) -> str | None:
        """The address this kind is reached at for what a person typed: the fixed one, else `typed` when it passes
        the address rule; None when it is not an address of this kind."""
        if self.fixed_address is not None:
            return self.fixed_address
        return None if typed is None else address.base_url(typed, self.schemes, self.pinned)


class ConnectionKinds(Service):
    """The registered kinds, in the order the panel shows them. Unregistered: none, so no connection can be made."""

    def __init__(self, kinds: tuple[ConnectionKind, ...] = ()) -> None:
        names = [k.name for k in kinds]
        if len(set(names)) != len(names):
            raise ValueError("two kinds share a name")
        self._kinds = {k.name: k for k in kinds}

    @classmethod
    def null(cls) -> "ConnectionKinds":
        return cls()

    def all(self) -> tuple[ConnectionKind, ...]:
        return tuple(self._kinds.values())

    def of_port(self, port: Port) -> tuple[ConnectionKind, ...]:
        """The registered kinds that implement `port`, in registration order."""
        return tuple(k for k in self._kinds.values() if port in k.ports)

    def get(self, name: str) -> ConnectionKind | None:
        return self._kinds.get(name)

    def offered(self, household_id: int) -> tuple[ConnectionKind, ...]:
        """The registered kinds `household_id` may connect, in registration order: every kind, less the `deployment`
        kinds for any household but `FIRST_HOUSEHOLD`."""
        return tuple(k for k in self._kinds.values() if not k.deployment or household_id == FIRST_HOUSEHOLD)

    def is_personal(self, name: str) -> bool:
        """Whether a connection of this kind made without saying who holds it is a person's own."""
        kind = self._kinds.get(name)
        return kind is not None and kind.default_holder == "person"
