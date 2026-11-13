"""The ModelCatalogue service (`ashley.services`): what each model costs and can do, from models.dev's list laid under
a person's overrides (`catalogue_merge`). The router prices every call through it and refuses, for a task that offers
tools, a model listed without tool calls. Callers name a model by its route's provider name; the catalogue provider it
is listed under comes from `catalogue.json` (`catalogue_config`).

A call is priced only from what is known: a missing price, a price listed as 0 that no person marked free, a usage
part (cache tokens, audio, characters) the model lists no price for, all record no cost, never $0. A provider that
`providers.json` marks `local` costs 0."""

from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..services import Service
from .catalogue_config import CatalogueConfig
from .catalogue_merge import LOCAL, Listing, Merged, Pricing, pricing, rates_for
from .model import Usage


class ModelCatalogueUnavailable(Exception):
    """The stored layers could not be read or written."""


@dataclass(frozen=True)
class CatalogueState:
    """The layers as read now: the merge, and when the snapshot was taken and the fetch made (None: there is none)."""

    merged: Merged
    snapshot_at: datetime | None
    fetched_at: datetime | None


class PricedCatalogue:
    """The merged layers as the router reads them, by route provider name."""

    def __init__(self, merged: Merged, config: CatalogueConfig) -> None:
        self.merged = merged
        self._config = config

    def listing(self, provider: str, model: str) -> Listing | None:
        return self.merged.listings.get((self._config.listed_as(provider), model))

    def pricing(self, provider: str, model: str) -> Pricing:
        if provider in self._config.local:
            return LOCAL
        return pricing(self.listing(provider, model))

    def cost_usd(self, provider: str, model: str, usage: Usage) -> Decimal | None:
        """The cost of one call, None when it cannot be known (see the module's rule)."""
        found = self.pricing(provider, model)
        if found.status in ("local", "free"):
            return Decimal(0)
        if found.status != "priced" or found.fields is None or usage.audio_ms or usage.characters:
            return None
        prompt = usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens
        rates = rates_for(found.fields, prompt)
        parts = ((usage.input_tokens, rates.input_usd_per_mtok), (usage.output_tokens, rates.output_usd_per_mtok),
                 (usage.cache_read_tokens, rates.cache_read_usd_per_mtok),
                 (usage.cache_write_tokens, rates.cache_write_usd_per_mtok))
        if any(tokens and rate is None for tokens, rate in parts):
            return None
        return sum((tokens * rate for tokens, rate in parts if tokens and rate is not None), Decimal(0)).scaleb(-6)

    def refuses_tools(self, provider: str, model: str) -> bool:
        """Whether the model is listed as making no tool calls; a model not listed is not refused."""
        found = self.listing(provider, model)
        return found is not None and found.fields.tool_call is False


class ModelCatalogue(Service):
    @classmethod
    def null(cls) -> "ModelCatalogue":
        return NullCatalogue()

    @abstractmethod
    async def refresh(self) -> None:
        """Bring the layers in force up to date when they are older than the implementation's bound; never raises."""

    @abstractmethod
    def priced(self) -> PricedCatalogue:
        """The layers in force, as last refreshed."""

    @abstractmethod
    async def state(self) -> CatalogueState:
        """The layers read now, not from the cache, which this read also refreshes. Raises ModelCatalogueUnavailable."""


class FixedCatalogue(ModelCatalogue):
    """Layers that never change: a process with no database, and tests."""

    def __init__(self, priced: PricedCatalogue, snapshot_at: datetime | None = None) -> None:
        self._priced = priced
        self._snapshot_at = snapshot_at

    async def refresh(self) -> None:
        return None

    def priced(self) -> PricedCatalogue:
        return self._priced

    async def state(self) -> CatalogueState:
        return CatalogueState(self._priced.merged, self._snapshot_at, None)


class NullCatalogue(ModelCatalogue):
    """What an unwired process sees: nothing listed, so every call is unpriced and none refused; `state` raises."""

    def __init__(self) -> None:
        self._priced = PricedCatalogue(Merged({}, {}), CatalogueConfig("https://unwired.invalid", 1, 1, 1, {}, frozenset()))

    async def refresh(self) -> None:
        return None

    def priced(self) -> PricedCatalogue:
        return self._priced

    async def state(self) -> CatalogueState:
        raise ModelCatalogueUnavailable("ModelCatalogue is not wired")
