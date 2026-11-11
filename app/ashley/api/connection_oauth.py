"""Connecting a service through its OAuth consent screen (`decisions.md`, "A kind's secret can come from OAuth"), as a
Discord account is linked (`ashley.api.accounts`).

`POST /api/connections/oauth/{provider}/start` begins a connect of a kind that declares that provider, bound to the
person who made it, and answers the consent URL for the page to send the browser to. The provider returns the browser to
`GET /api/connections/oauth/{provider}/callback`, which takes the connect once, within sign-in's `pending_minutes`, and
only for the person who started it, then stores the connection only after the kind's own check answers with the new
access token. It returns to `/connections?connect=<outcome>`: `connected`, `cancelled` (declined at the provider),
`wrong_person`, `refused` (the check did not answer with it), `label_taken`, `too_many`, `unavailable`, or `failed`. A
person who connects again under the label of a connection they hold replaces its tokens and clears its `needs`. The
callback is the one cookie-carrying GET that writes, since the provider can only return with a GET.

One log line per start, connect and refusal, with household and person ids, the kind and a connection id; never a
token, code, state or address."""

import logging
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import logs, services
from ..connections.connections import Connections, ConnectionsUnavailable, LabelTaken, TooMany
from ..connections.kinds import ConnectionKind, ConnectionKinds, OAuth
from ..connections.oauth import CALLBACK_PATH, OAuthFailed, OAuthProvider, OAuthProviders, OAuthUnavailable
from ..connections.oauth_connections import OAuthConnections
from ..connections.pending import ConnectPending, Pending
from ..signin.oidc import pkce
from . import connection_holders
from .connection_models import OAuthStartRequest, OAuthStartResponse
from .admin_gate import may_change, refused
from .models import ErrorResponse
from .person import Person, callback_person

router = APIRouter()
log = logging.getLogger("ashley.api")
Outcome = Literal["connected", "cancelled", "wrong_person", "refused", "label_taken", "too_many", "unavailable",
                  "failed"]
_START: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site; `admin_only`: a "
          "`deployment` kind, which only an admin connects"},
    404: {"model": ErrorResponse, "description": "`not_found`: no such kind, or it is not connected through that "
          "provider"},
    422: {"model": ErrorResponse, "description": "`unsupported`: a personal kind held by the household; or a body "
          "outside the request's schema, which gets FastAPI's own validation error"},
    503: {"model": ErrorResponse, "description": "`unavailable`: connections or the provider are not set up here, the "
          "database could not be reached, or too many connects are in flight"}}


_WHO = {"household": "the household", "person": "a person"}


def _error(status: int, code: Literal["not_found", "unavailable", "unsupported"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "connecting is unavailable right now; try again shortly")


def _oauth_kind(name: str, provider: str) -> ConnectionKind | None:
    kind = services.get(ConnectionKinds).get(name)
    return kind if kind is not None and isinstance(kind.connect, OAuth) and kind.connect.provider == provider else None


@router.post("/api/connections/oauth/{provider}/start", status_code=201, response_model=OAuthStartResponse,
             responses=_START)
async def start_oauth_connect(signed_in: Person, provider: str, body: OAuthStartRequest) -> OAuthStartResponse | JSONResponse:
    """201 `OAuthStartResponse`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 422 `unsupported`; 503
    `unavailable`, also when too many connects are in flight at once."""
    person = signed_in.person
    kind = _oauth_kind(body.kind, provider)
    if kind is None or not isinstance(kind.connect, OAuth):
        return _error(404, "not_found", "there is no such kind of connection")
    if body.holder not in kind.holders:
        return _error(422, "unsupported", f"{kind.title} cannot be held by {_WHO[body.holder]}")
    if not may_change(signed_in, kind):
        return refused(signed_in, "connections.oauth")
    registered = services.get(OAuthProviders).get(provider)
    if registered is None or not services.get(Connections).can_open():
        return _unavailable()
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce()
    try:
        begun = await services.get(ConnectPending).begin(
            state, Pending(person.household_id, person.id, kind.name, body.label, body.holder, verifier))
    except ConnectionsUnavailable:
        return _unavailable()
    if not begun:
        logs.warning(log, "connections.oauth_refused", reason="too_many_in_flight", person=person.id)
        return _unavailable()
    logs.info(log, "connections.oauth_started", household=person.household_id, person=person.id, kind=kind.name)
    return OAuthStartResponse(authorize_url=registered.authorize_url(state, challenge, kind.connect.scopes))


def _back(outcome: Outcome, reason: str, **fields: object) -> RedirectResponse:
    logs.info(log, "connections.connected" if outcome == "connected" else "connections.oauth_refused", reason=reason,
              **fields)
    return RedirectResponse(f"/connections?connect={outcome}", status_code=302)


async def _store(pending: Pending, kind: ConnectionKind, provider: OAuthProvider, code: str) -> Outcome | int:
    """The id of the connection stored for what `code` is worth, else the outcome that says why not. Raises
    OAuthFailed, OAuthUnavailable and ConnectionsUnavailable."""
    grant = await provider.redeem(code, pending.verifier)
    base = kind.base_url(None)
    if base is None or grant.refresh_token is None:
        return "failed"
    refusal = await kind.check(base, grant.access_token, pending.person_id)
    if refusal is not None:
        return "unavailable" if refusal == "unreachable" else "refused"
    held = await services.get(Connections).of_household(pending.household_id, pending.person_id)
    mine = pending.person_id if pending.holder == "person" else None
    again = next((c for c in held if c.kind == kind.name and c.label == pending.label and c.person_id == mine), None)
    stored = services.get(OAuthConnections)
    try:
        if again is not None:
            replaced = await stored.replace_oauth(again.id, pending.household_id, pending.person_id, base, grant)
            return "failed" if replaced is None else replaced.id
        added = await stored.add_oauth(pending.household_id, kind.name, pending.label, base, grant, pending.person_id,
                                       pending.holder)
        return added.id
    except LabelTaken:
        return "label_taken"
    except TooMany:
        return "too_many"


@router.get(CALLBACK_PATH, response_class=RedirectResponse, status_code=302)
async def finish_oauth_connect(request: Request) -> Response:
    """302 to `/connections?connect=<outcome>` (the module docstring). Reads the provider's `state`, `code` and `error`
    from the query and the provider from the path, undeclared, so no value is ever a 422: a browser on its way back
    gets a page."""
    provider = str(request.path_params["provider"])
    signed_in = await callback_person(request)
    if isinstance(signed_in, str):
        return _back(signed_in, "not_signed_in" if signed_in == "failed" else "sessions_down")
    person = signed_in.person
    state, code, error = (request.query_params.get(k) for k in ("state", "code", "error"))
    try:
        pending = await services.get(ConnectPending).take(state) if state else None
        if pending is None:
            return _back("failed", "state_unknown_or_expired", person=person.id)
        if pending.person_id != person.id:
            return _back("wrong_person", "wrong_person", person=person.id, started_by=pending.person_id)
        kind, registered = _oauth_kind(pending.kind, provider), services.get(OAuthProviders).get(provider)
        if kind is None or registered is None:
            return _back("failed", "provider_not_set_up", person=person.id)
        if error or not code:
            return _back("cancelled", "declined", person=person.id) if error == "access_denied" \
                else _back("failed", "provider_error" if error else "no_code", person=person.id)
        stored = await _store(pending, kind, registered, code)
    except OAuthFailed as e:
        return _back("failed", "code_refused", person=person.id, why=str(e))
    except (OAuthUnavailable, ConnectionsUnavailable) as e:
        return _back("unavailable", type(e).__name__, person=person.id)
    if isinstance(stored, str):
        return _back(stored, "not_stored", person=person.id, kind=kind.name)
    await connection_holders.stored(stored, person.household_id, person.id)
    return _back("connected", "ok", household=person.household_id, person=person.id, kind=kind.name, connection=stored)
