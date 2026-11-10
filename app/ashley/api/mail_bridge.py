"""What Proton Bridge's keeper calls, under `/api/mail-bridge/keeper` (`decisions.md`, "Bridge runs as a leased singleton
whose vault outlives its pod"). The keeper has no session: its credential is the token minted for its epoch, sent as
`Authorization: Bearer`, whose SHA-256 the record keeps, and every call names its epoch.

- `GET /vault?epoch=N`: 200 `KeeperVault`, what Bridge starts from.
- `PUT /vault`: 200 `Written`, a write-back, taken only at the generation the keeper read and the current epoch.
- `POST /heartbeat`: 204, the pod is alive; the answer an old pod stops Bridge on.
- `POST /events`: 200 `Applied`, an account's state or sync event.

Refusals: 401 `unauthorized` (a token that is not the epoch's), 409 `refused` (the epoch is not current, or a write-back is
at a generation the record has moved past), 503 `unavailable` (the database is unreachable or read-only). A keeper treats
the 409 and the 503 alike: it stops Bridge. Logs `proton_bridge.written_back` (epoch, generation, bytes),
`proton_bridge.refused` (epoch, call, reason) and `proton_bridge.sync` (epoch, account id, event); never a token, an address
or the vault."""

import base64
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response
from fastapi.responses import JSONResponse

from .. import logs, services
from ..mail.proton_bridge import BridgeUnavailable, ProtonBridge
from .mail_bridge_models import Applied, Heartbeat, KeeperEvent, KeeperVault, VaultWrite, Written
from .models import ErrorResponse

router = APIRouter()
log = logging.getLogger("ashley.api")
PREFIX = "/api/mail-bridge/keeper"
_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: not the token of that epoch"},
    409: {"model": ErrorResponse, "description": "`refused`: the epoch is not current, or the generation is stale"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the record cannot be written"},
    422: {"model": ErrorResponse, "description": "a body or query outside the schema gets FastAPI's own validation "
          "error, which is not this schema"}}
Bearer = Annotated[str | None, Header(alias="Authorization")]


def _error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


async def _refusal(call: str, epoch: int, authorization: str | None) -> JSONResponse | None:
    """The refusal for a call naming `epoch` with this header, or None when it is the current epoch's keeper."""
    token = authorization[7:] if authorization is not None and authorization.startswith("Bearer ") else ""
    try:
        auth = await services.get(ProtonBridge).authorize(epoch, token)
    except BridgeUnavailable:
        logs.warning(log, "proton_bridge.refused", epoch=epoch, call=call, reason="unavailable")
        return _error(503, "unavailable", "the record cannot be reached")
    if auth == "ok":
        return None
    logs.warning(log, "proton_bridge.refused", epoch=epoch, call=call, reason=auth)
    if auth == "stale_epoch":
        return _error(409, "refused", "that epoch is not current")
    return _error(401, "unauthorized", "not the token of that epoch")


@router.get(PREFIX + "/vault", response_model=KeeperVault, responses=_ERRORS)
async def read_vault(epoch: Annotated[int, Query()], authorization: Bearer = None) -> KeeperVault | JSONResponse:
    """200 `KeeperVault`; 401; 409 `refused`, the epoch is not current; 503 `unavailable`."""
    refused = await _refusal("vault_read", epoch, authorization)
    if refused is not None:
        return refused
    try:
        got = await services.get(ProtonBridge).vault(epoch)
    except BridgeUnavailable:
        return _error(503, "unavailable", "the record cannot be reached")
    if got is None:
        return _error(409, "refused", "that epoch is not current")
    enc = base64.b64encode
    return KeeperVault(generation=got.generation, vault=None if got.vault is None else enc(got.vault).decode(),
                       keychain=None if got.keychain is None else enc(got.keychain).decode())


@router.put(PREFIX + "/vault", response_model=Written, responses=_ERRORS)
async def write_vault(body: VaultWrite, authorization: Bearer = None) -> Written | JSONResponse:
    """200 `Written`; 401; 409 `refused`, the epoch is not current or the generation is stale; 503 `unavailable`."""
    refused = await _refusal("write_back", body.epoch, authorization)
    if refused is not None:
        return refused
    try:
        generation = await services.get(ProtonBridge).write_back(
            body.epoch, body.generation, base64.b64decode(body.vault), base64.b64decode(body.keychain))
    except BridgeUnavailable:
        logs.warning(log, "proton_bridge.refused", epoch=body.epoch, call="write_back", reason="unavailable")
        return _error(503, "unavailable", "the record cannot be written")
    if generation is None:
        logs.warning(log, "proton_bridge.refused", epoch=body.epoch, call="write_back", reason="stale_generation")
        return _error(409, "refused", "the record has moved past that generation")
    logs.info(log, "proton_bridge.written_back", epoch=body.epoch, generation=generation, bytes=len(body.vault))
    return Written(generation=generation)


@router.post(PREFIX + "/heartbeat", status_code=204, response_class=Response, responses=_ERRORS)
async def heartbeat(body: Heartbeat, authorization: Bearer = None) -> Response:
    """204; 401; 409 `refused`, the epoch is not current; 503 `unavailable`."""
    refused = await _refusal("heartbeat", body.epoch, authorization)
    if refused is not None:
        return refused
    try:
        current = await services.get(ProtonBridge).heartbeat(body.epoch, body.certificate_sha256)
    except BridgeUnavailable:
        logs.warning(log, "proton_bridge.refused", epoch=body.epoch, call="heartbeat", reason="unavailable")
        return _error(503, "unavailable", "the record cannot be written")
    return Response(status_code=204) if current else _error(409, "refused", "that epoch is not current")


@router.post(PREFIX + "/events", response_model=Applied, responses=_ERRORS)
async def event(body: KeeperEvent, authorization: Bearer = None) -> Applied | JSONResponse:
    """200 `Applied`; 401; 409 `refused`; 503 `unavailable`."""
    refused = await _refusal("event", body.epoch, authorization)
    if refused is not None:
        return refused
    bridge = services.get(ProtonBridge)
    try:
        if body.state is not None:
            account = await bridge.set_state(body.epoch, body.user_id, body.state)
        else:
            assert body.sync is not None
            account = await bridge.sync(body.epoch, body.user_id, body.sync, body.progress)
    except BridgeUnavailable:
        return _error(503, "unavailable", "the record cannot be written")
    logs.info(log, "proton_bridge.sync", epoch=body.epoch, account=account, kind=body.sync or body.state)
    return Applied(applied=account is not None)
