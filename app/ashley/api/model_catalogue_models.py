"""The wire models of the model catalogue's admin routes (`ashley.api.model_catalogue`, `api-contract-first`): what each
model costs and can do, upstream's value beside a person's for every field, and the layers' ages. Prices are USD per
million tokens; a price that is null is not known, never 0."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..inference.catalogue_merge import PriceStatus
from ..inference.catalogue_model import FIELD_NAMES, FieldName

Price = float | None


class ModelCatalogueTier(BaseModel):
    """The prices a prompt longer than `above_prompt_tokens` pays (input, cache-read and cache-write tokens together)."""

    above_prompt_tokens: int
    input_usd_per_mtok: Price
    output_usd_per_mtok: Price
    cache_read_usd_per_mtok: Price
    cache_write_usd_per_mtok: Price


class ModelCatalogueFields(BaseModel):
    """One model's fields; null is not known. `free` and `hidden` are a person's only; `tiers` come from upstream only,
    and a person's price on any price field replaces them."""

    name: str | None
    tool_call: bool | None
    structured_output: bool | None
    context_tokens: int | None
    max_output_tokens: int | None
    input_usd_per_mtok: Price
    output_usd_per_mtok: Price
    cache_read_usd_per_mtok: Price
    cache_write_usd_per_mtok: Price
    free: bool | None
    hidden: bool | None
    tiers: list[ModelCatalogueTier]


class ModelCatalogueOverride(BaseModel):
    """A field a person set: who (`set_by`, a person id, null once they are gone) and when."""

    field_name: FieldName
    set_by: int | None
    set_at: datetime


class ModelCataloguePrice(BaseModel):
    """How a call to the model is priced. `status`: `priced`; `unpriced` (no price known, so a call records no cost);
    `listed_zero` (upstream lists 0, recorded as no cost until a person marks the model `free`); `free` (a person said
    so: a call costs 0). `source_layer`: the layer the prices in force came from, null when unpriced."""

    status: PriceStatus
    source_layer: Literal["snapshot", "fetch", "override"] | None


class ModelCatalogueModel(BaseModel):
    """One model. `fields` are in force; `defaults` are upstream's, from `defaults_layer`, null for a model only a person lists;
    `overrides` the fields a person set, each reset by naming it in a change's `reset`."""

    provider: str
    model: str
    fields: ModelCatalogueFields
    defaults: ModelCatalogueFields | None
    defaults_layer: Literal["snapshot", "fetch"] | None
    overrides: list[ModelCatalogueOverride]
    price: ModelCataloguePrice


class ModelCatalogueProvider(BaseModel):
    """A provider in the catalogue: its id, its name, its OpenAI-compatible base URL where it lists one, how many models
    it lists and how many of those carry an override. `has_connection`: whether the deployment holds a model-provider
    connection priced as it (the first household's, not a key only the env holds); null when the connections could not
    be read."""

    provider: str
    name: str
    api: str | None
    model_count: int
    overridden_count: int
    has_connection: bool | None


class ModelCatalogueResponse(BaseModel):
    """Every provider, by id. `snapshot_taken_at`: when the list baked into the image was fetched; `fetched_at`: when
    the last good fetch was made, which replaces the snapshot; either null when there is none. A fetch is tried every
    `refresh_s` seconds."""

    snapshot_taken_at: datetime | None
    fetched_at: datetime | None
    refresh_s: int
    catalogue_providers: list[ModelCatalogueProvider]


class ModelCatalogueModelsResponse(BaseModel):
    """The models of one provider, by id."""

    provider: str
    models: list[ModelCatalogueModel]


class ModelCatalogueSet(BaseModel):
    """The fields a person sets; a field left out or null is not changed. A value equal to upstream's is not stored:
    it resets the field, so upstream's later changes reach it."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    tool_call: bool | None = None
    structured_output: bool | None = None
    context_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    input_usd_per_mtok: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_usd_per_mtok: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_read_usd_per_mtok: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_write_usd_per_mtok: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    free: bool | None = None
    hidden: bool | None = None


class ModelCatalogueChange(BaseModel):
    """A change to one model, for the whole deployment: `set` these fields and `reset` those to upstream's. A model
    upstream does not list is added by setting its fields."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    set: ModelCatalogueSet
    reset: list[FieldName] = Field(default_factory=list[FieldName], max_length=len(FIELD_NAMES))


class ModelCatalogueRefused(BaseModel):
    """Why nothing was stored: `set_and_reset` (one field both set and reset), `empty` (nothing set or reset)."""

    reason: Literal["set_and_reset", "empty"]
    detail: str
