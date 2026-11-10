"""A signed-in person's own accounts, and linking their Discord account through Discord's OAuth2 (`decisions.md`, "A
person links their own Discord account").

`POST /api/accounts/discord/link` starts a link bound to the person who made it and answers Discord's authorization
URL for the page to send the browser to. Discord returns the browser to `GET /api/accounts/discord/callback`, which
takes that link once, within sign-in's `pending_minutes`, and only for the person who started it; it writes the
`discord` account and returns to `/connections?link=<outcome>`: `linked`, `cancelled` (declined at Discord), `taken`
(another person has that Discord account), `wrong_person` (the link was started by someone other than who is signed in
now), `unavailable`, or `failed`. The callback is the one cookie-carrying GET that writes: Discord can only return with
a GET, and its state was made by a same-origin POST for this person alone. `DELETE /api/accounts/{account_id}` unlinks
one of the person's Discord accounts.

One log line per start, link, refusal and unlink, with person ids and a 12-hex hash of the Discord user id; never a
token, code, state or handle."""

import logging
import secrets
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import logs, services
from ..people.accounts import Accounts
from ..people.model import Account
from ..people.people import PeopleUnavailable
from ..signin.discord import CALLBACK_PATH, SYSTEM, DiscordOAuth, LinkFailed, LinkUnavailable
from ..signin.identity import sub_prefix
from ..signin.model import LinkPending
from ..signin.oidc import pkce
from ..signin.sessions import Sessions, SessionsUnavailable
from .models import AccountsResponse, ErrorResponse, LinkedAccount, LinkStartResponse
from .person import Person, callback_person

router = APIRouter()
log = logging.getLogger("ashley.api")
Outcome = Literal["linked", "cancelled", "taken", "wrong_person", "unavailable", "failed"]
_AccountId = Annotated[int, Path(ge=1)]
_DOWN = (PeopleUnavailable, SessionsUnavailable, LinkUnavailable)
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: linking is not configured, or Discord or the "
          "database could not be reached"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN, 403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"}}


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "linking accounts is unavailable right now; try again shortly")


def _wire(account: Account) -> LinkedAccount:
    return LinkedAccount(id=account.id, system=account.system, handle=account.handle or None,
                         unlinkable=account.system == SYSTEM)


@router.get("/api/accounts", response_model=AccountsResponse, responses=_SIGNED_IN)
async def list_accounts(signed_in: Person) -> AccountsResponse | JSONResponse:
    """200 `AccountsResponse`; 401 `unauthorized`; 503 `unavailable`."""
    try:
        accounts = await services.get(Accounts).of(signed_in.person.id)
    except PeopleUnavailable:
        return _unavailable()
    return AccountsResponse(accounts=[_wire(a) for a in accounts],
                            discord_linking=services.get(DiscordOAuth).configured())


@router.post("/api/accounts/discord/link", status_code=201, response_model=LinkStartResponse, responses=_WRITE)
async def start_discord_link(signed_in: Person) -> LinkStartResponse | JSONResponse:
    """201 `LinkStartResponse`; 401 `unauthorized`; 403 `forbidden`; 503 `unavailable`, also when too many links are
    in flight at once."""
    person = signed_in.person
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce()
    try:
        url = await services.get(DiscordOAuth).authorize_url(state, challenge)
        if not await services.get(Sessions).begin_link(state, LinkPending(person.household_id, person.id, verifier)):
            logs.warning(log, "link.refused", reason="too_many_in_flight", person=person.id)
            return _unavailable()
    except (LinkUnavailable, SessionsUnavailable) as e:
        logs.warning(log, "link.unavailable", step="start", why=type(e).__name__)
        return _unavailable()
    logs.info(log, "link.started", person=person.id, system=SYSTEM)
    return LinkStartResponse(authorize_url=url)


def _back(outcome: Outcome, reason: str, **fields: object) -> RedirectResponse:
    logs.info(log, "link.ok" if outcome == "linked" else "link.refused", reason=reason, **fields)
    return RedirectResponse(f"/connections?link={outcome}", status_code=302)


@router.get(CALLBACK_PATH, response_class=RedirectResponse, status_code=302)
async def finish_discord_link(request: Request) -> Response:
    """302 to `/connections?link=<outcome>` (the module docstring). Reads Discord's `state`, `code` and `error` from the
    query, undeclared, so no value is ever a 422: a browser on its way back gets a page."""
    signed_in = await callback_person(request)
    if isinstance(signed_in, str):
        return _back(signed_in, "not_signed_in" if signed_in == "failed" else "sessions_down")
    person = signed_in.person
    state, code, error = (request.query_params.get(k) for k in ("state", "code", "error"))
    try:
        pending = await services.get(Sessions).take_link(state) if state else None
        if pending is None:
            return _back("failed", "state_unknown_or_expired", person=person.id)
        if pending.person_id != person.id:
            return _back("wrong_person", "wrong_person", person=person.id, started_by=pending.person_id)
        if error or not code:
            return _back("cancelled", "declined", person=person.id) if error == "access_denied" \
                else _back("failed", "provider_error" if error else "no_code", person=person.id)
        user = await services.get(DiscordOAuth).identify(code, pending.verifier)
        linked = await services.get(Accounts).link(person.id, SYSTEM, user.id, user.handle)
    except LinkFailed as e:
        return _back("failed", "token_refused", person=person.id, why=str(e))
    except _DOWN as e:
        return _back("unavailable", type(e).__name__, person=person.id)
    return _back(linked, "ok" if linked == "linked" else "taken", person=person.id, discord=sub_prefix(user.id))


@router.delete("/api/accounts/{account_id}", status_code=204, response_class=Response, responses={
    **_WRITE, 404: {"model": ErrorResponse, "description": "`not_found`: no Discord account of yours has that id"},
    422: {"model": ErrorResponse, "description": "an account id below 1 gets FastAPI's own validation error, which "
          "is not this schema"}})
async def unlink_account(signed_in: Person, account_id: _AccountId) -> Response:
    """204, unlinked; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 503 `unavailable`."""
    person = signed_in.person
    try:
        gone = await services.get(Accounts).unlink(person.id, account_id, SYSTEM)
    except PeopleUnavailable:
        return _unavailable()
    if not gone:
        return _error(404, "not_found", "no such account of yours")
    logs.info(log, "link.unlinked", person=person.id, account=account_id, system=SYSTEM)
    return Response(status_code=204)
