"""Sign-in through OIDC, and who is signed in (`decisions.md`, "People sign in through OIDC").

`GET /api/auth/signin?next=/path` sends the browser to the provider; the provider sends it back to `GET /api/auth/callback`,
which must carry the state this browser was sent with (its cookie), once, within the policy's `pending_minutes`, so a
callback from someone else's sign-in never signs this browser in. A sign-in returns to `next`; one refused returns to
`/?signin=failed`, or `/?signin=unmapped` when the provider vouched for an account no person here has yet (the admin
maps it: `python -m ashley.signin unmapped`). A sign-in also settles who is an admin (`decisions.md`, "An admin changes
what the deployment shares"): the provider's admin group, when one is configured, says so for this person; otherwise,
if nobody is an admin, the earliest person of the first household becomes one. `POST /api/auth/signout` ends the
session; `GET /api/me` names the person. Unconfigured or unreachable, sign-in answers 503 and the rest of the app runs.

One log line per sign-in, refusal and sign-out, with session and person ids and, for an unmapped account, a 12-hex
hash of its sub; never a token, code, state, email or username."""

import logging
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import logs, services
from ..connections.kinds import FIRST_HOUSEHOLD
from ..people.admins import Admins
from ..people.people import PeopleUnavailable
from ..signin import policy as signin_policy
from ..signin.identity import SYSTEM, sub_prefix
from ..signin.model import Identity, Pending
from ..signin.oidc import Oidc, OidcUnavailable, SignInFailed, pkce
from ..signin.sessions import Sessions, SessionsUnavailable
from .models import ErrorResponse, MeResponse, wire_person
from .person import SESSION_COOKIE, SIGNIN_COOKIE, CrossSite, Person, clear_cookie, same_site, set_cookie

router = APIRouter()
log = logging.getLogger("ashley.api")
_POLICY = signin_policy.load()
_UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"model": ErrorResponse, "description": "`unavailable`: sign-in is not configured, or the provider "
                      "or the database could not be reached"}}


def safe_next(raw: str | None) -> str:
    """Only a path on this site: never another host (`//evil`, `/\\evil`, `https://...`), never a control character."""
    if not raw or len(raw) > 512 or not raw.startswith("/") or raw.startswith(("//", "/\\")) or any(ord(c) < 32 for c in raw):
        return "/"
    return raw


_OAUTH_ERRORS = frozenset({
    "invalid_request", "unauthorized_client", "access_denied", "unsupported_response_type", "invalid_scope",
    "server_error", "temporarily_unavailable", "interaction_required", "login_required", "account_selection_required",
    "consent_required", "invalid_request_uri", "invalid_request_object", "request_not_supported",
    "request_uri_not_supported", "registration_not_supported"})


def _oauth_error(raw: str) -> str:
    """The provider's `error` as an RFC 6749 / OIDC error code, or `other`: the query is the browser's to write, so
    nothing else of it reaches the log."""
    return raw if raw in _OAUTH_ERRORS else "other"


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=503, content=ErrorResponse(
        code="unavailable", detail="sign-in is unavailable right now; try again shortly").model_dump())


def _refused(reason: str, outcome: Literal["failed", "unmapped"] = "failed", **fields: object) -> RedirectResponse:
    logs.info(log, "signin.refused", reason=reason, **fields)
    response = RedirectResponse(f"/?signin={outcome}", status_code=302)
    clear_cookie(response, SIGNIN_COOKIE)
    return response


@router.get("/api/auth/signin", response_class=RedirectResponse, status_code=302, responses=_UNAVAILABLE)
async def start_signin(request: Request) -> Response:
    """302 to the provider, with this sign-in's state in a cookie; 503 `unavailable`. The query's `next` is a path on this
    site to return to once signed in; anything else returns to `/`. Query parameters are read, not declared, so no
    value is ever a 422: a browser on its way to sign in gets a sign-in."""
    next = request.query_params.get("next")
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    verifier, challenge = pkce()
    try:
        url = await services.get(Oidc).authorize_url(state, nonce, challenge)
        if not await services.get(Sessions).begin(state, Pending(verifier, nonce, safe_next(next))):
            logs.warning(log, "signin.refused", reason="too_many_in_flight")
            return _unavailable()
    except (OidcUnavailable, SessionsUnavailable) as e:
        logs.warning(log, "signin.unavailable", step="start", why=type(e).__name__)
        return _unavailable()
    response = RedirectResponse(url, status_code=302)
    set_cookie(response, SIGNIN_COOKIE, state, _POLICY.pending_minutes * 60)
    return response


@router.get("/api/auth/callback", response_class=RedirectResponse, status_code=302, responses=_UNAVAILABLE)
async def finish_signin(request: Request) -> Response:
    """302 to the sign-in's `next` with a session cookie; 302 to `/?signin=failed` or `/?signin=unmapped` when
    refused; 503 `unavailable`. Reads the provider's `state`, `code` and `error` from the query, undeclared, as
    `start_signin` does."""
    state = request.query_params.get("state", "")
    code, error = request.query_params.get("code"), request.query_params.get("error")
    mine = request.cookies.get(SIGNIN_COOKIE, "")
    if not state or not mine or not secrets.compare_digest(mine.encode(), state.encode()):
        return _refused("state_mismatch")
    try:
        pending = await services.get(Sessions).take(state)
        if pending is None:
            return _refused("state_unknown_or_expired")
        if error or not code:
            return _refused("provider_error", error=_oauth_error(error)) if error else _refused("no_code")
        identity = await services.get(Oidc).identify(code, pending.verifier, pending.nonce)
        return await _open(request, identity, pending.next)
    except SignInFailed as e:
        return _refused("token_refused", why=str(e))
    except (OidcUnavailable, SessionsUnavailable) as e:
        logs.warning(log, "signin.unavailable", step="callback", why=type(e).__name__)
        return _unavailable()


async def _one_admin() -> None:
    """While the app decides who is an admin, make sure someone is (`Admins.ensure_one`). A failure leaves the sign-in
    standing; the next sign-in tries again."""
    try:
        await services.get(Admins).ensure_one(FIRST_HOUSEHOLD)
    except PeopleUnavailable as e:
        logs.warning(log, "signin.admin_unchecked", why=type(e).__name__)


async def _open(request: Request, identity: Identity, to: str) -> Response:
    sessions = services.get(Sessions)
    opened = await sessions.open(SYSTEM, identity.sub, identity.admin_group)
    if opened is None:
        await sessions.refused(SYSTEM, identity.sub, identity.username)
        return _refused("unmapped", "unmapped", sub=sub_prefix(identity.sub))
    if identity.admin_group is None:
        await _one_admin()
    old = request.cookies.get(SESSION_COOKIE, "")
    if old:
        await sessions.close(old)
    signed_in = opened.signed_in
    logs.info(log, "signin.ok", session=signed_in.session_id, person=signed_in.person.id,
              household=signed_in.person.household_id, admin=signed_in.person.admin)
    response = RedirectResponse(to, status_code=302)
    clear_cookie(response, SIGNIN_COOKIE)
    set_cookie(response, SESSION_COOKIE, opened.token, _POLICY.session_days * 86400)
    return response


@router.post("/api/auth/signout", status_code=204, response_class=Response, responses={
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"}, **_UNAVAILABLE})
async def sign_out(request: Request) -> Response:
    """204, the session ended and its cookie cleared, signed in or not; 403 `forbidden`; 503 `unavailable`."""
    if not same_site(request):
        logs.info(log, "signin.cross_site", method=request.method)
        raise CrossSite()
    token = request.cookies.get(SESSION_COOKIE, "")
    try:
        ended = await services.get(Sessions).close(token)
    except SessionsUnavailable:
        return _unavailable()
    if ended is not None:
        logs.info(log, "signout", session=ended.session_id, person=ended.person.id)
    response = Response(status_code=204)
    clear_cookie(response, SESSION_COOKIE)
    return response


@router.get("/api/me", response_model=MeResponse, responses={
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"}, **_UNAVAILABLE})
async def get_me(signed_in: Person) -> MeResponse:
    """200 `MeResponse`; 401 `unauthorized`; 503 `unavailable`."""
    return MeResponse(person=wire_person(signed_in.person))
