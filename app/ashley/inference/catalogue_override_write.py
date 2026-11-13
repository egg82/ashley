"""The CatalogueOverrideWriter service (`ashley.services`): a person sets or resets fields of one model, for the whole
deployment. Kept apart from the reads, so nothing she does on her own changes a price or a capability: only the
catalogue's web route and the wiring import this module (`tests/test_settings_boundary.py`).

What to write is decided before this, by `catalogue_merge.delta`, so a field set to upstream's value is reset, not
stored."""

from abc import abstractmethod
from collections.abc import Collection, Mapping

from ..services import Service
from .catalogue import ModelCatalogueUnavailable
from .catalogue_model import FieldName


class CatalogueOverrideWriter(Service):
    @classmethod
    def null(cls) -> "CatalogueOverrideWriter":
        return NullCatalogueOverrideWriter()

    @abstractmethod
    async def write(self, provider: str, model: str, put: Mapping[FieldName, object], reset: Collection[FieldName],
                    person_id: int) -> None:
        """In one transaction, store each of `put` (values held as `catalogue_model.field_value` returns them) as set by
        `person_id`, and delete each of `reset`. Logs `catalogue.override_set` (provider, model, person, the count put
        and reset; never a value). Raises ModelCatalogueUnavailable."""


class NullCatalogueOverrideWriter(CatalogueOverrideWriter):
    """What an unwired process sees: every write raises ModelCatalogueUnavailable."""

    async def write(self, provider: str, model: str, put: Mapping[FieldName, object], reset: Collection[FieldName],
                    person_id: int) -> None:
        raise ModelCatalogueUnavailable("CatalogueOverrideWriter is not wired")
