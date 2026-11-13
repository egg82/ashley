"""Model catalogues for tests: the shipped config over an excerpt of models.dev's real `api.json`
(`models_dev_captured/api.json`, captured 2026-11-13: Anthropic's, OpenAI's and Google's routed models plus edge cases),
and catalogues built from values."""

import json
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from ashley.inference import catalogue_config, models_dev
from ashley.inference.catalogue import FixedCatalogue, PricedCatalogue
from ashley.inference.catalogue_config import CatalogueConfig
from ashley.inference.catalogue_merge import Override, merged
from ashley.inference.catalogue_model import Catalogue, ModelFields, Provider

CAPTURED = Path(__file__).with_name("models_dev_captured") / "api.json"
PLAIN = CatalogueConfig("https://example.test/api.json", 60, 10, 5, {}, frozenset({"here"}))


def captured() -> Catalogue:
    return models_dev.parse(json.loads(CAPTURED.read_text())).catalogue


def shipped(overrides: tuple[Override, ...] = ()) -> FixedCatalogue:
    """The shipped `catalogue.json` over the captured list as the fetched layer."""
    return FixedCatalogue(PricedCatalogue(merged(captured(), "fetch", overrides), catalogue_config.load()))


def of(models: Mapping[str, Mapping[str, ModelFields]], config: CatalogueConfig = PLAIN,
       overrides: tuple[Override, ...] = ()) -> FixedCatalogue:
    """A catalogue listing `models[provider][model]` as fetched."""
    catalogue = Catalogue({p: Provider(p, None, dict(ms)) for p, ms in models.items()})
    return FixedCatalogue(PricedCatalogue(merged(catalogue, "fetch", overrides), config))


def flat(inp: str = "3", out: str = "15", read: str | None = "0.3", write: str | None = "3.75",
         tool_call: bool | None = True) -> ModelFields:
    """A model priced flat, USD per million tokens."""
    return ModelFields(name="m", tool_call=tool_call, input_usd_per_mtok=Decimal(inp), output_usd_per_mtok=Decimal(out),
                       cache_read_usd_per_mtok=None if read is None else Decimal(read),
                       cache_write_usd_per_mtok=None if write is None else Decimal(write))


NONE = of({})
