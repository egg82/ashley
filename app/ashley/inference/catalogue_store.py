"""Where the catalogue's stored layers are kept: the last good fetch, replaced whole by the refresh singleton
(`catalogue_refresh`), and a person's overrides, which only `catalogue_override_write` writes."""

from abc import ABC, abstractmethod
from datetime import datetime

from .catalogue_merge import Override
from .catalogue_model import Catalogue


class CatalogueStore(ABC):
    @abstractmethod
    async def fetched_at(self) -> datetime | None:
        """When the stored fetch was made; None when there is none. Raises ModelCatalogueUnavailable."""

    @abstractmethod
    async def fetched(self) -> tuple[Catalogue, datetime] | None:
        """The stored fetch and when it was made. Raises ModelCatalogueUnavailable."""

    @abstractmethod
    async def put_fetch(self, catalogue: Catalogue, at: datetime) -> None:
        """Replace the stored fetch. Raises ModelCatalogueUnavailable."""

    @abstractmethod
    async def overrides(self) -> list[Override]:
        """Every field a person set. Raises ModelCatalogueUnavailable."""
