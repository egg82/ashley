"""The wire models of a household's connections (`ashley.api.connections`), apart from `models` for size. No model
carries a connection's secret outward: the key or token goes in once, in a `ConnectionRequest`, and is
never returned."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from ..text import NoNul
from .models import Person

Label = Annotated[NoNul, StringConstraints(strip_whitespace=True, max_length=40)]
"""What an owner calls a connection: stripped of surrounding whitespace, at most 40 characters, empty allowed."""


class ConnectionResource(BaseModel):
    """What a connection reaches, as its service names it: `ref` is the service's own id (a mailbox's address) and
    addresses it, `kind` what it is (`mailbox`), `name` what to show. `shared` says the household may use it; false,
    only the connection's owner may."""

    ref: str
    kind: Literal["mailbox"]
    name: str
    shared: bool


class HouseholdConnection(BaseModel):
    """One of the household's connections. `id` is what addresses it; `label` is what its owner calls it, empty for one
    never named. `kind` is the service, the `name` of a registered connection kind; `base_url` where it is
    reached; `added_by` the person who added it, null once they are not among the household's people or for one
    carried over from her own setup; `personal` whether it is the signed-in person's own (a code host) and not the
    household's; `checked_at` when the service last answered with it, at its adding or on one of
    her reads since. `needs` is set while its person must act before it works again (`reconnect`: the service
    refused its grant, so connect it again); `scopes` are what an OAuth service granted and `missing_scopes` what its kind asks for
    that it did not (a person unticked them), empty for a pasted kind. `resources` is what it reaches, each shared or
    kept (none for a kind that lists none). `can_hand_over` says the signed-in person may hand it to the household
    (it is theirs and its kind allows the household to hold it); `can_take_back` that they may take it back (they
    added it and its kind allows a person to hold it). `can_change` says they may replace, rename, remove or set it
    up: false for a deployment's connection (a model provider's key) unless they are an admin. `catalogue_provider` is
    the model catalogue provider an OpenAI-compatible provider's calls are priced as, null for one at a custom address
    (its calls are unpriced) and for every other kind."""

    id: int
    label: str
    kind: str
    base_url: str
    added_by: Person | None
    added_at: datetime
    checked_at: datetime
    personal: bool
    needs: Literal["reconnect", "login"] | None = None
    scopes: list[str] = []
    missing_scopes: list[str] = []
    resources: list[ConnectionResource] = []
    can_hand_over: bool = False
    can_take_back: bool = False
    can_change: bool = True
    catalogue_provider: str | None = None


class ConnectionKindInfo(BaseModel):
    """A kind of connection a household or person can make, as its adapter declares it: what the panel shows for it
    and what the request must carry. `name` is the `kind` of a new connection; `most` is how many of it one owner may hold; `title` and `what` label it; `blurb`,
    `connected` and `removed` are what the panel says before and after; `holders` is who may hold one, the household,
    a person (`person`) or either, and a new connection of a kind a person may hold is theirs until they hand it over;
    `takes_address` whether a person types its address (`address_placeholder` shows the shape); `secret_field` is the
    request field that carries the key or token, `secret_label` what to call it to a person and `secret_noun` its
    name in a button. `connect` is how it is connected: `pasted`, a person types the secret, or `oauth`, through the
    service's own consent screen (`POST /api/connections/oauth/{provider}/start`), or `bridge`, a login to the service's account
    made once from the room (`POST /api/mail-bridge/login`); `set_up` is whether this app can
    connect it at all (an OAuth kind whose client is not configured is not); `has_settings` whether a person sets anything on a connection of
    it (`GET /api/connections/{id}/settings`). `label_pattern`, when set, is the shape a label of it must match whole
    (an OpenAI-compatible provider's label is the name routes call it by, so it is required and an identifier); some
    names a shipped provider has are refused too (422 `bad_label`). `picks_catalogue_provider` says a new connection
    may name the model catalogue provider it is (`GET /api/catalogue`), whose `api` is its address; without one it is
    at a custom address and its calls are unpriced."""

    name: str
    title: str
    what: str
    blurb: str
    connected: str
    removed: str
    holders: list[Literal["household", "person"]]
    most: int
    takes_address: bool
    address_placeholder: str
    secret_field: Literal["api_key", "token"]
    secret_label: str
    secret_noun: str
    connect: Literal["pasted", "oauth", "bridge"] = "pasted"
    set_up: bool = True
    has_settings: bool = False
    label_pattern: str | None = None
    picks_catalogue_provider: bool = False


class ConnectionsResponse(BaseModel):
    """The signed-in person's household's connections, by kind, and every kind they can connect, in the order to show
    them (a model provider's key only for an admin of the deployment's first household, whose keys pay for every call). `can_connect` is whether this app holds the key that seals them; false, none can be added and
    `connections` is empty."""

    connections: list[HouseholdConnection]
    offered: list[ConnectionKindInfo]
    can_connect: bool


class ApiKeyConnectionRequest(BaseModel):
    """Replace a connection of a kind whose `secret_field` is `api_key` (Sure, a model provider): `base_url` is the
    address it is served at, left out for a kind that has one address (a model provider's); `api_key` is a key made in
    the service's own settings, checked against it before anything is stored. `catalogue_provider`, only for a kind
    that `picks_catalogue_provider`, is the model catalogue provider (`GET /api/catalogue`) its calls are priced as;
    left out, a custom address whose calls are unpriced."""

    base_url: NoNul | None = Field(default=None, min_length=1, max_length=500)
    api_key: NoNul = Field(min_length=1, max_length=500, pattern=r"^\S+$")
    catalogue_provider: NoNul | None = Field(default=None, min_length=1, max_length=100)


class TokenConnectionRequest(BaseModel):
    """Replace a connection of a kind whose `secret_field` is `token` (Home Assistant, GitLab, GitHub): `base_url` is
    the address it is served at, left out for a kind that has one address (GitHub's); `token` is the access token,
    checked against the service before anything is stored."""

    base_url: NoNul | None = Field(default=None, min_length=1, max_length=500)
    token: NoNul = Field(min_length=1, max_length=500, pattern=r"^\S+$")


class NewApiKeyConnectionRequest(ApiKeyConnectionRequest):
    """A new connection of the registered `kind`, called `label`, with an `api_key`."""

    kind: NoNul
    label: Label


class NewTokenConnectionRequest(TokenConnectionRequest):
    """A new connection of the registered `kind`, called `label`, with a `token`."""

    kind: NoNul
    label: Label


ConnectionRequest = ApiKeyConnectionRequest | TokenConnectionRequest
"""What `PUT /api/connections/{id}` takes: the body whose secret field is the kind's own (`ConnectionKindInfo.secret_field`)."""

NewConnectionRequest = NewApiKeyConnectionRequest | NewTokenConnectionRequest
"""What `POST /api/connections` takes: the same, with the kind and label."""


class ConnectionChange(BaseModel):
    """`PATCH /api/connections/{id}`: either the new `label`, or the new `holder`: `household` hands the connection to
    the household, `person` takes back one the signed-in person handed over. Exactly one of them."""

    label: Label | None = None
    holder: Literal["household", "person"] | None = None

    @model_validator(mode="after")
    def _one(self) -> "ConnectionChange":
        if (self.label is None) == (self.holder is None):
            raise ValueError("send a label or a holder, not both and not neither")
        return self


class ResourceShare(BaseModel):
    """`PATCH /api/connections/{id}/resources/{ref}`: `shared` true shares the resource with the household, false keeps
    it for the connection's owner."""

    shared: bool


class ConnectionRefused(BaseModel):
    """Why a connection was not stored; nothing was. `reason`: `bad_url`, the address is not one the service may be
    reached at (a scheme the kind allows, a host, no credentials, query or fragment); `key_refused`, the service turned
    the key or token away; `unreachable`, nothing answered there in time, or it redirected or failed; `wrong_service`,
    what answered is not that service's API. `detail` is the kind's own words for a person."""

    reason: Literal["bad_url", "key_refused", "unreachable", "wrong_service"]
    detail: str


class OAuthStartRequest(BaseModel):
    """Start connecting an OAuth `kind` under `label`, held by `holder`: the household's or the person's own, as the
    kind allows (`ConnectionKindInfo.holders`)."""

    kind: NoNul
    label: Label
    holder: Literal["household", "person"] = "person"


class OAuthStartResponse(BaseModel):
    """Where to send this browser to connect: the service's consent page, which returns it to
    `/connections?connect=<outcome>`. Good for one connect, within sign-in's `pending_minutes`."""

    authorize_url: str
