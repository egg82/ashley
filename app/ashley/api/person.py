"""A person signed in with a session cookie: `person_signed_in`, the dependency every route for a person uses, as
`messages.signed_in` is for a device. The cookie is `__Host-` (Secure, Path=/, no Domain, so no other host can set or
read it), HttpOnly and SameSite=Lax; its value is the session token, which is never logged.

A write made with the cookie (any method but GET, HEAD and OPTIONS) must come from this site, which closes the
cross-site requests SameSite=Lax lets through. Its `Origin` must be `public_url`'s; with no `Origin`, a
`Sec-Fetch-Site` naming another site is refused (every browser sends one or the other on a cross-site write, so a
write with neither is no browser riding someone's cookie). A body must be JSON, or a WAV or raw bytes on the routes that take one
(`person_speaking`, `person_uploading`); a plain cross-site form can send neither, and a cross-site fetch of either is preflighted. A GET
made with the cookie never changes anything, but for the Discord link's callback, which Discord can only return to
with a GET (`ashley.api.accounts`), and the connections room's OAuth callback (`ashley.api.connection_oauth`)."""

import logging
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse

from .. import logs, services
from ..signin.model import SignedIn
from ..signin.sessions import Sessions, SessionsUnavailable
from .models import ErrorResponse

log = logging.getLogger("ashley.api")

SESSION_COOKIE = "__Host-ashley_session"
SIGNIN_COOKIE = "__Host-ashley_signin"   # the state of the sign-in in flight, matching the callback to this browser
_READS = frozenset({"GET", "HEAD", "OPTIONS"})


class NotSignedIn(Exception):
    """No live session; `main` answers it with 401 `unauthorized`."""


class CrossSite(Exception):
    """A cookie-signed write from another site, or not JSON; `main` answers it with 403 `forbidden`."""


class SessionsDown(Exception):
    """The session could not be read for want of the database; `main` answers it with 503 `unavailable`."""


def _error(status: int, code: Literal["unauthorized", "forbidden", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


async def not_signed_in(_: Request, __: Exception) -> JSONResponse:
    return _error(401, "unauthorized", "sign in")


async def cross_site(_: Request, __: Exception) -> JSONResponse:
    return _error(403, "forbidden", "a change must come from this site, as JSON")


async def sessions_down(_: Request, __: Exception) -> JSONResponse:
    return _error(503, "unavailable", "sign-in is unavailable right now; try again shortly")


JSON = "application/json"
WAV = "audio/wav"
BYTES = "application/octet-stream"


def same_site(request: Request, body_type: str = JSON) -> bool:
    """Whether a write comes from this site, in a body a cross-site form cannot send (the module docstring): `body_type`,
    JSON unless the route takes another, never one a form can send."""
    origin = request.headers.get("origin")
    if origin is not None:
        public: str = request.app.state.settings.public_url
        theirs = urlsplit(origin)
        ours = urlsplit(public)
        if not public or (theirs.scheme, theirs.netloc.lower()) != (ours.scheme, ours.netloc.lower()):
            return False
    elif request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return False
    has_body = request.headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in request.headers
    kind = request.headers.get("content-type")
    if kind is None:
        return not has_body
    return kind.split(";")[0].strip().lower() == body_type


async def person_signed_in(request: Request) -> SignedIn:
    """The person this browser's session signs in. A write is checked for its site first, so a forged one reads
    nothing. Raises CrossSite, NotSignedIn or SessionsDown."""
    return await _signed_in(request, JSON)


async def person_speaking(request: Request) -> SignedIn:
    """`person_signed_in` for a write whose body is a WAV (`spoken`) rather than JSON."""
    return await _signed_in(request, WAV)


async def person_uploading(request: Request) -> SignedIn:
    """`person_signed_in` for a write whose body is raw bytes (`bench_files`): a form cannot send that type, and a
    cross-site fetch of it is preflighted."""
    return await _signed_in(request, BYTES)


async def _signed_in(request: Request, body_type: str) -> SignedIn:
    if request.method not in _READS and not same_site(request, body_type):
        logs.info(log, "signin.cross_site", method=request.method)
        raise CrossSite()
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        raise NotSignedIn()
    try:
        signed_in = await services.get(Sessions).find(token)
    except SessionsUnavailable as e:
        raise SessionsDown() from e
    if signed_in is None:
        raise NotSignedIn()
    return signed_in


async def callback_person(request: Request) -> SignedIn | Literal["failed", "unavailable"]:
    """The person signed in now, for a callback a browser returns to with a GET (an OAuth link or connect); else the
    outcome for one no person can be found for: `failed` with no live session, `unavailable` with no database."""
    try:
        return await person_signed_in(request)
    except NotSignedIn:
        return "failed"
    except SessionsDown:
        return "unavailable"


Person = Annotated[SignedIn, Depends(person_signed_in)]
Speaking = Annotated[SignedIn, Depends(person_speaking)]
Uploading = Annotated[SignedIn, Depends(person_uploading)]


def set_cookie(response: Response, name: str, value: str, max_age_s: int) -> None:
    response.set_cookie(name, value, max_age=max_age_s, path="/", secure=True, httponly=True, samesite="lax")


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
