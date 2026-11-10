"""Logging a Proton account in to Bridge from the connections room, and the accounts Bridge holds
(`decisions.md`, "Logging in happens once, from the room").

`POST /api/mail-bridge/login` takes the label, Proton username and password; `POST /api/mail-bridge/login/verified` the password again once
the person has passed Proton's human check (answered by `human_verification` with its page), `POST
/api/mail-bridge/login/two-factor` the code and `POST /api/mail-bridge/login/mailbox-password` the second password of an account that has two, each with the label.
Each relays one step to Bridge through `ProtonLogin` and answers `ProtonLoginStep`: what to ask next, or `connected`, when
the connection is stored with the password Bridge issued as its secret and its addresses are known. A person who logs in
again to an account they hold (signed out) replaces its secret and clears its `needs`. What is typed is passed on and
forgotten: never stored, never logged. `GET /api/mail-bridge/accounts` lists the Proton accounts of the connections the
person can see, with their state and whether Bridge is still syncing them.

Refusals: 400 `ProtonLoginRefused` (Bridge turned the step down, the label is taken, or the person holds as many as the
kind allows; the login is over), 404 `not_found` (Proton is not set up here), 503 `unavailable` (no Bridge is running, or the
database cannot be reached). One log line per step with household and person ids and the outcome."""

import logging
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import logs, services
from ..connections.connections import Connections, ConnectionsUnavailable, LabelTaken, TooMany
from ..connections.kinds import ConnectionKinds
from ..connections.resource_sync import sync
from ..mail.proton_bridge import BridgeUnavailable, ProtonBridge
from ..mail.proton_kind import ADDRESS, NAME
from ..mail.proton_login import Ask, Done, LoginStep, ProtonLogin, Refused, Verify
from .mail_bridge_models import (ProtonAccount, ProtonAccounts, ProtonLoginRefused, ProtonLoginStart, ProtonLoginStep,
                                 ProtonMailboxPassword, ProtonSecondFactor, ProtonVerifiedLogin)
from .models import ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ProtonLoginRefused, "description": "Bridge or the app turned the step down; the login is over"},
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    403: {"model": ErrorResponse, "description": "`forbidden`: the request came from another site"},
    404: {"model": ErrorResponse, "description": "`not_found`: Proton is not set up here"},
    503: {"model": ErrorResponse, "description": "`unavailable`: no Bridge is running, or the database is unreachable"},
    422: {"model": ErrorResponse, "description": "a body or query outside the schema gets FastAPI's own validation "
          "error, which is not this schema"}}
_DETAIL = {"credentials": "Proton did not accept that username and password", "code": "Proton did not accept that code",
           "mailbox_password": "Proton did not accept that mailbox password", "label_taken": "you already have a Proton "
           "account under that name", "too_many": "you already have as many Proton accounts as can be connected",
           "paid_plan": "Bridge needs a paid Proton plan", "connection": "Bridge could not reach Proton; try again",
           "aborted": "Bridge ended that login; start again", "verification": "Proton's check did not pass; try again",
           "security_key": "this account's two-factor is a security key only; Bridge needs an authenticator-app code",
           "other": "Bridge could not log that account in"}


def _refused(reason: Literal["credentials", "code", "mailbox_password", "paid_plan", "connection", "aborted",
                             "verification", "security_key", "label_taken", "too_many", "other"],
             person: Person) -> JSONResponse:
    logs.info(log, "proton_bridge.login", household=person.person.household_id, person=person.person.id, outcome=reason)
    return JSONResponse(status_code=400, content=ProtonLoginRefused(reason=reason, detail=_DETAIL[reason]).model_dump())


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "Proton is unavailable right now; try again shortly")


def _set_up() -> bool:
    kind = services.get(ConnectionKinds).get(NAME)
    return kind is not None and kind.configured and services.get(Connections).can_open()


async def _store(signed_in: Person, label: str, done: Done) -> int | Literal["label_taken", "too_many"]:
    """The id of the connection now holding the account: the one the person already holds for that Proton user, else a new
    one, unless the label is another account's. Raises ConnectionsUnavailable and BridgeUnavailable."""
    person = signed_in.person
    connections, bridge = services.get(Connections), services.get(ProtonBridge)
    held = [c for c in await connections.of_household(person.household_id, person.id) if c.kind == NAME]
    users = {a.connection_id: a.proton_user_id for a in await bridge.accounts()}
    again = next((c for c in held if users.get(c.id) == done.user_id), None)
    if again is None and any(c.label == label for c in held):
        return "label_taken"
    try:
        if again is not None:
            replaced = await connections.replace(again.id, person.household_id, person.id, ADDRESS, done.bridge_password)
            stored = again.id if replaced is not None else None
        else:
            stored = (await connections.add(person.household_id, NAME, label, ADDRESS, done.bridge_password,
                                            person.id)).id
    except LabelTaken:
        return "label_taken"
    except TooMany:
        return "too_many"
    if stored is None:
        return "label_taken"
    await bridge.add_account(stored, done.user_id, done.addresses, done.epoch if done.synced else 0)
    opened = await connections.opened(stored, person.household_id, person.id)
    if opened is not None:
        await sync(opened)
    return stored


async def _answer(signed_in: Person, label: str, step: LoginStep) -> ProtonLoginStep | JSONResponse:
    person = signed_in.person
    if isinstance(step, Refused):
        return _refused(step.reason, signed_in)
    if isinstance(step, Verify):
        logs.info(log, "proton_bridge.login", household=person.household_id, person=person.id,
                  outcome="human_verification")
        return ProtonLoginStep(step="human_verification", verification_url=step.url)
    if isinstance(step, Ask):
        logs.info(log, "proton_bridge.login", household=person.household_id, person=person.id, outcome=step.step)
        return ProtonLoginStep(step=step.step)
    try:
        stored = await _store(signed_in, label, step)
    except (BridgeUnavailable, ConnectionsUnavailable):
        await _forget(step.user_id)
        return _unavailable()
    if isinstance(stored, str):
        await _forget(step.user_id)
        return _refused(stored, signed_in)
    logs.info(log, "proton_bridge.login", household=person.household_id, person=person.id, outcome="connected",
              connection=stored)
    return ProtonLoginStep(step="connected", connection_id=stored, addresses=list(step.addresses))


async def _forget(user_id: str) -> None:
    try:
        await services.get(ProtonLogin).forget(user_id)
    except BridgeUnavailable:
        logs.warning(log, "proton_bridge.forget_failed")


async def _relay(signed_in: Person, label: str, ask: Any) -> ProtonLoginStep | JSONResponse:
    if not _set_up():
        return _error(404, "not_found", "Proton is not set up here")
    try:
        return await _answer(signed_in, label, await ask())
    except BridgeUnavailable:
        return _unavailable()


async def _room_for(signed_in: Person, label: str) -> JSONResponse | None:
    """The refusal when the person holds as many Proton accounts as allowed and none under `label`, else None."""
    person = signed_in.person
    kind = services.get(ConnectionKinds).get(NAME)
    try:
        held = [c for c in await services.get(Connections).of_household(person.household_id, person.id)
                if c.kind == NAME]
    except ConnectionsUnavailable:
        return _unavailable()
    if kind is not None and len(held) >= kind.most and not any(c.label == label for c in held):
        return _refused("too_many", signed_in)
    return None


@router.post("/api/mail-bridge/login", response_model=ProtonLoginStep, responses=_ERRORS)
async def start_login(signed_in: Person, body: ProtonLoginStart) -> ProtonLoginStep | JSONResponse:
    """200 `ProtonLoginStep`; 400 `ProtonLoginRefused`; 401; 403; 404 `not_found`; 503 `unavailable`."""
    if not _set_up():
        return _error(404, "not_found", "Proton is not set up here")
    full = await _room_for(signed_in, body.label)
    if full is not None:
        return full
    login = services.get(ProtonLogin)
    return await _relay(signed_in, body.label, lambda: login.begin(body.username, body.password))


@router.post("/api/mail-bridge/login/verified", response_model=ProtonLoginStep, responses=_ERRORS)
async def verified_login(signed_in: Person, body: ProtonVerifiedLogin) -> ProtonLoginStep | JSONResponse:
    """200 `ProtonLoginStep`; 400 `ProtonLoginRefused`; 401; 403; 404 `not_found`; 503 `unavailable`."""
    login = services.get(ProtonLogin)
    return await _relay(signed_in, body.label, lambda: login.verified(body.password))


@router.post("/api/mail-bridge/login/two-factor", response_model=ProtonLoginStep, responses=_ERRORS)
async def second_factor(signed_in: Person, body: ProtonSecondFactor) -> ProtonLoginStep | JSONResponse:
    """200 `ProtonLoginStep`; 400 `ProtonLoginRefused`; 401; 403; 404 `not_found`; 503 `unavailable`."""
    login = services.get(ProtonLogin)
    return await _relay(signed_in, body.label, lambda: login.second_factor(body.code))


@router.post("/api/mail-bridge/login/mailbox-password", response_model=ProtonLoginStep, responses=_ERRORS)
async def mailbox_password(signed_in: Person, body: ProtonMailboxPassword) -> ProtonLoginStep | JSONResponse:
    """200 `ProtonLoginStep`; 400 `ProtonLoginRefused`; 401; 403; 404 `not_found`; 503 `unavailable`."""
    login = services.get(ProtonLogin)
    return await _relay(signed_in, body.label, lambda: login.mailbox_password(body.password))


@router.get("/api/mail-bridge/accounts", response_model=ProtonAccounts, responses={
    401: _ERRORS[401], 503: _ERRORS[503]})
async def list_proton_accounts(signed_in: Person) -> ProtonAccounts | JSONResponse:
    """200 `ProtonAccounts`: the Proton accounts of the connections the person can see; 401; 503 `unavailable`."""
    person = signed_in.person
    try:
        visible = {c.id for c in await services.get(Connections).of_household(person.household_id, person.id)}
        held = await services.get(ProtonBridge).accounts()
    except (BridgeUnavailable, ConnectionsUnavailable):
        return _unavailable()
    return ProtonAccounts(proton_accounts=[ProtonAccount(
        connection_id=a.connection_id, state=a.state, addresses=list(a.addresses), syncing=a.syncing,
        sync_progress=a.sync_progress) for a in held if a.connection_id in visible])
