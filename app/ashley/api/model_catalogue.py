"""The model catalogue's admin routes (`decisions.md`, "An override stores only what a person changed"): what each model
costs and can do, for the whole deployment, so only an admin of the first household reads or changes it. Only this
route and the wiring reach `CatalogueOverrideWriter`, so nothing she does on her own changes a price.

`GET /api/catalogue` answers every provider and the layers' ages; `GET /api/catalogue/models?provider=` one provider's
models, each field in force beside upstream's with who set each override; `PUT /api/catalogue/models` sets and resets
fields of one model and answers it as stored. A change reaches every call's pricing within `stored_catalogue.REFRESH_S`.

One log line per write (the writer's `catalogue.override_set`) and one per refusal (`catalogue.change_refused`)."""

import logging
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .. import logs, services
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.kinds import FIRST_HOUSEHOLD, ConnectionKinds
from ..inference import catalogue_config
from ..inference.catalogue import ModelCatalogue, ModelCatalogueUnavailable
from ..inference.catalogue_merge import Listing, delta, pricing
from ..inference.catalogue_model import FIELD_NAMES, FieldName, ModelFields, Tier, field_value
from ..inference.catalogue_override_write import CatalogueOverrideWriter
from ..signin.model import SignedIn
from .admin_gate import ADMIN_ONLY, refused
from .model_catalogue_models import (ModelCatalogueChange, ModelCatalogueFields, ModelCatalogueModel,
                                     ModelCatalogueModelsResponse, ModelCatalogueOverride, ModelCataloguePrice,
                                     ModelCatalogueProvider, ModelCatalogueRefused, ModelCatalogueResponse,
                                     ModelCatalogueTier)
from .models import ErrorResponse
from .person import Person

router = APIRouter()
log = logging.getLogger("ashley.api")
_READ: dict[int | str, dict[str, Any]] = {
    **ADMIN_ONLY,
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the stored layers could not be read or written"}}
_MODELS: dict[int | str, dict[str, Any]] = {
    **_READ,
    404: {"model": ErrorResponse, "description": "`not_found`: the catalogue lists no such provider"},
    422: {"model": ErrorResponse, "description": "a parameter outside its bounds gets FastAPI's own validation error, "
          "which is not this schema"}}
_WRITE: dict[int | str, dict[str, Any]] = {
    **_READ,
    422: {"model": ModelCatalogueRefused, "description": "a change that cannot be made; nothing was stored. A body "
          "outside the request's schema gets FastAPI's own validation error, which is not this schema"}}
ProviderId = Annotated[str, Query(min_length=1, max_length=100)]


def _error(status: int, code: Literal["not_found", "unavailable"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def _unavailable() -> JSONResponse:
    return _error(503, "unavailable", "the model catalogue is unavailable right now; try again shortly")


def _deployment_admin(signed_in: SignedIn) -> bool:
    return signed_in.person.admin and signed_in.person.household_id == FIRST_HOUSEHOLD


def _price(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _tier(t: Tier) -> ModelCatalogueTier:
    return ModelCatalogueTier(above_prompt_tokens=t.above_prompt_tokens, input_usd_per_mtok=_price(t.input_usd_per_mtok),
                              output_usd_per_mtok=_price(t.output_usd_per_mtok),
                              cache_read_usd_per_mtok=_price(t.cache_read_usd_per_mtok),
                              cache_write_usd_per_mtok=_price(t.cache_write_usd_per_mtok))


def _fields(f: ModelFields) -> ModelCatalogueFields:
    return ModelCatalogueFields(
        name=f.name, tool_call=f.tool_call, structured_output=f.structured_output, context_tokens=f.context_tokens,
        max_output_tokens=f.max_output_tokens, input_usd_per_mtok=_price(f.input_usd_per_mtok),
        output_usd_per_mtok=_price(f.output_usd_per_mtok), cache_read_usd_per_mtok=_price(f.cache_read_usd_per_mtok),
        cache_write_usd_per_mtok=_price(f.cache_write_usd_per_mtok), free=f.free, hidden=f.hidden,
        tiers=[_tier(t) for t in f.tiers])


def _model(listing: Listing) -> ModelCatalogueModel:
    priced = pricing(listing)
    source = priced.source if priced.source in ("snapshot", "fetch", "override") else None
    return ModelCatalogueModel(
        provider=listing.provider, model=listing.model, fields=_fields(listing.fields),
        defaults=None if listing.default is None else _fields(listing.default),
        defaults_layer=listing.layer if listing.layer in ("snapshot", "fetch") else None,
        overrides=[ModelCatalogueOverride(field_name=o.field, set_by=o.set_by, set_at=o.set_at)
                   for o in sorted(listing.overrides.values(), key=lambda o: FIELD_NAMES.index(o.field))],
        price=ModelCataloguePrice(status=priced.status, source_layer=source))


async def _connected() -> frozenset[str] | None:
    """The catalogue providers the first household's model-provider connections are priced as (a keyed kind as its
    route name is listed, an OpenAI-compatible one as it names); None when the connections cannot be read."""
    try:
        held = await services.get(Connections).of_household(FIRST_HOUSEHOLD)
    except ConnectionsUnavailable:
        return None
    kinds = {k.name for k in services.get(ConnectionKinds).of_port("inference")}
    config = catalogue_config.load()
    return frozenset(c.catalogue_provider or config.listed_as(c.kind) for c in held if c.kind in kinds)


@router.get("/api/catalogue", response_model=ModelCatalogueResponse, responses=_READ)
async def read_catalogue(signed_in: Person) -> ModelCatalogueResponse | JSONResponse:
    """200 `ModelCatalogueResponse`; 401 `unauthorized`; 403 `admin_only`; 503 `unavailable`."""
    if not _deployment_admin(signed_in):
        return refused(signed_in, "catalogue")
    try:
        state = await services.get(ModelCatalogue).state()
    except ModelCatalogueUnavailable:
        return _unavailable()
    counts: dict[str, list[int]] = {}
    for (pid, _), listing in state.merged.listings.items():
        count = counts.setdefault(pid, [0, 0])
        count[0] += 1
        count[1] += bool(listing.overrides)
    connected = await _connected()
    providers = [ModelCatalogueProvider(provider=pid, name=p.name, api=p.api, model_count=counts.get(pid, [0, 0])[0],
                                        overridden_count=counts.get(pid, [0, 0])[1],
                                        has_connection=None if connected is None else pid in connected)
                 for pid, p in sorted(state.merged.providers.items())]
    return ModelCatalogueResponse(snapshot_taken_at=state.snapshot_at, fetched_at=state.fetched_at,
                                  refresh_s=round(catalogue_config.load().refresh_s), catalogue_providers=providers)


@router.get("/api/catalogue/models", response_model=ModelCatalogueModelsResponse, responses=_MODELS)
async def read_models(signed_in: Person, provider: ProviderId) -> ModelCatalogueModelsResponse | JSONResponse:
    """200 `ModelCatalogueModelsResponse`; 401 `unauthorized`; 403 `admin_only`; 404 `not_found`; 503
    `unavailable`."""
    if not _deployment_admin(signed_in):
        return refused(signed_in, "catalogue")
    try:
        state = await services.get(ModelCatalogue).state()
    except ModelCatalogueUnavailable:
        return _unavailable()
    if provider not in state.merged.providers:
        return _error(404, "not_found", "the catalogue lists no such provider")
    found = sorted((m for (pid, m) in state.merged.listings if pid == provider))
    return ModelCatalogueModelsResponse(provider=provider,
                                        models=[_model(state.merged.listings[(provider, m)]) for m in found])


@router.put("/api/catalogue/models", response_model=ModelCatalogueModel, responses=_WRITE)
async def change_model(signed_in: Person, body: ModelCatalogueChange) -> ModelCatalogueModel | JSONResponse:
    """200 `ModelCatalogueModel` as stored; 401 `unauthorized`; 403 `admin_only` or `forbidden`; 422
    `ModelCatalogueRefused`; 503 `unavailable`."""
    if not _deployment_admin(signed_in):
        return refused(signed_in, "catalogue")
    put: dict[FieldName, object] = {f: field_value(f, v) for f in FIELD_NAMES
                                    if (v := getattr(body.set, f)) is not None}
    why = "set_and_reset" if set(put) & set(body.reset) else "empty" if not put and not body.reset else None
    if why is not None:
        logs.info(log, "catalogue.change_refused", person=signed_in.person.id, reason=why)
        detail = "a field cannot be both set and reset" if why == "set_and_reset" else "nothing to set or reset"
        return JSONResponse(status_code=422, content=ModelCatalogueRefused(reason=why, detail=detail).model_dump())
    catalogue = services.get(ModelCatalogue)
    try:
        before = (await catalogue.state()).merged.listings.get((body.provider, body.model))
        stored, deleted = delta(None if before is None else before.default, put, body.reset)
        await services.get(CatalogueOverrideWriter).write(body.provider, body.model, stored, deleted,
                                                          signed_in.person.id)
        after = (await catalogue.state()).merged.listings.get((body.provider, body.model))
    except ModelCatalogueUnavailable:
        return _unavailable()
    if after is None:
        return JSONResponse(status_code=422, content=ModelCatalogueRefused(
            reason="empty", detail="the catalogue lists no such model and nothing was set on it").model_dump())
    return _model(after)
