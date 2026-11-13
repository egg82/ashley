"""A household's connection to a service outside her, as values."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Kind = str
"""Which service a connection reaches: the `name` of a registered `ashley.connections.kinds.ConnectionKind`. A
household or person holds up to the kind's `most` of one kind, each under its own label."""

Needs = Literal["reconnect", "login"]
"""What a connection needs from its person before it works again: `reconnect`, its OAuth grant was refused (revoked or
expired); `login`, a Proton account its Bridge signed out."""

Holder = Literal["household", "person"]
"""Who holds a connection: the household, or one person (`Connection.person_id` says which)."""

ResourceKind = Literal["mailbox"]
"""What a connection reaches, as its service names it."""

Port = Literal["house", "ledger", "code_host", "herdr", "mail", "inference", "search", "chat"]
"""What a service is for: the question a consumer asks, whichever service answers it. A kind declares the ports it
implements (`ConnectionKind.ports`); a consumer opens a port, never a kind."""


@dataclass(frozen=True)
class Connection:
    """One household's connection of `kind`, as it is shown: never its secret. `added_by` is the person who added
    it (None once they are no longer in the household's people, or for one seeded from her own setup); `checked_at` is when the service last answered
    with it, at its adding or on a read since. `person_id` is whose it is, set for the personal kinds and None for the
    household's. `label` is what its owner calls it ("work"), empty for one never named. `needs` is set while it
    cannot be used until its person acts, and `scopes` are the OAuth scopes its service granted (none for a pasted
    secret). `catalogue_provider` is the model catalogue provider a model provider's calls are priced as, where its
    kind takes one (`ConnectionKind.picks_catalogue_provider`) and a person picked one; None otherwise."""

    id: int
    household_id: int
    kind: Kind
    base_url: str
    added_by: int | None
    added_at: datetime
    checked_at: datetime
    person_id: int | None = None
    label: str = ""
    needs: Needs | None = None
    scopes: tuple[str, ...] = ()
    catalogue_provider: str | None = None


@dataclass(frozen=True)
class Listed:
    """A resource as its service names it: `ref` is the service's own id for it (a mailbox's address), `name` what the
    room shows."""

    ref: str
    kind: ResourceKind
    name: str


@dataclass(frozen=True)
class CatalogueEntity:
    """A thing a service has, as a setting picks it: `id` (`domain.object_id`), `name` to show, `domain` and the
    service's `device_class` for it (None when it gives none)."""

    id: str
    name: str
    domain: str
    device_class: str | None


@dataclass(frozen=True)
class CatalogueAction:
    """An action a service offers (`domain.name`); `looks_up_only` when the service says it only returns data and
    changes nothing."""

    name: str
    domain: str
    looks_up_only: bool


@dataclass(frozen=True)
class Catalogued:
    """Everything a service has now that a setting may pick: its entities and its actions."""

    entities: tuple[CatalogueEntity, ...]
    actions: tuple[CatalogueAction, ...]


@dataclass(frozen=True)
class Resource:
    """A resource of a connection, stored: `shared` says the household may use it, `kept` (not shared) that only the
    connection's owner may."""

    ref: str
    kind: ResourceKind
    name: str
    shared: bool


@dataclass(frozen=True)
class Opened:
    """A connection with its secret unsealed, for the code that calls the service and nothing else. The secret is
    left out of `repr`, so a log line or a traceback that prints this cannot carry it."""

    connection: Connection
    secret: str = field(repr=False)


@dataclass(frozen=True)
class Grant:
    """What an OAuth provider handed back: the `access_token`, valid for `expires_in_s`, the `refresh_token` (None when
    the provider kept the old one), and the `scopes` it says it granted. Tokens are left out of `repr`."""

    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    expires_in_s: int
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class OAuthState:
    """An OAuth connection as renewal reads it: `opened` carries the refresh token as its secret; `access_token` is the
    sealed-at-rest access token unsealed (None when none is stored) with `expires_in_s` left on it by the database's
    clock; `version` is the row's `secret_version`, which a write of new tokens must still find."""

    opened: Opened
    access_token: str | None = field(repr=False)
    expires_in_s: float | None
    version: int
