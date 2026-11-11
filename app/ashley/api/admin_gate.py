"""The admin gate (`decisions.md`, "An admin changes what the deployment shares"): what only an admin may change, and the
one answer anyone else gets, 403 `admin_only`. A route that is admin-only as a whole takes `Admin` as its signed-in
person; a route whose target decides (a connection of a `deployment` kind) asks `may_change` and answers `admin_only()`.
The client hiding an action is never the check; this is."""

import logging
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from .. import logs
from ..connections.kinds import ConnectionKind
from ..signin.model import SignedIn
from .models import ErrorResponse
from .person import person_signed_in

log = logging.getLogger("ashley.api")
DETAIL = "only an admin of this deployment can change that"
ADMIN_ONLY: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorResponse, "description": "`admin_only`: only an admin may change that; `forbidden`: the "
          "request came from another site"}}


class NotAdmin(Exception):
    """A signed-in person who is not an admin asked for an admin's change; `main` answers it with 403 `admin_only`."""


def admin_only() -> JSONResponse:
    return JSONResponse(status_code=403, content=ErrorResponse(code="admin_only", detail=DETAIL).model_dump())


async def not_admin(_: Request, __: Exception) -> JSONResponse:
    return admin_only()


def may_change(signed_in: SignedIn, kind: ConnectionKind) -> bool:
    """Whether the signed-in person may add, replace, rename, remove or set up a connection of `kind`: any person for a
    household's or a person's kind, only an admin for a `deployment` kind."""
    return not kind.deployment or signed_in.person.admin


def refused(signed_in: SignedIn, what: str) -> JSONResponse:
    """`admin_only()`, logged with the person and what they asked to change."""
    logs.info(log, "admin.refused", person=signed_in.person.id, household=signed_in.person.household_id, what=what)
    return admin_only()


async def admin_signed_in(request: Request) -> SignedIn:
    """`person_signed_in` for a route only an admin may use. Raises NotAdmin, and what `person_signed_in` raises."""
    signed_in = await person_signed_in(request)
    if not signed_in.person.admin:
        logs.info(log, "admin.refused", person=signed_in.person.id, household=signed_in.person.household_id,
                  what=request.method)
        raise NotAdmin()
    return signed_in


Admin = Annotated[SignedIn, Depends(admin_signed_in)]
