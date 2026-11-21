"""The catalogue's stored layers in Postgres: tables `model_catalogue_fetch` (one row) and `model_catalogue_overrides`
(one row per field of one model). Contract: `catalogue_store.CatalogueStore`; the override writer is
`postgres_catalogue_override_write`. The stored fetch is read into records off the event loop: the whole list takes
about half a second."""

import asyncio
import logging
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import get_args

import psycopg
from psycopg.types.json import Jsonb

from .. import logs
from ..db.database import Database, DatabaseUnavailable
from .catalogue import ModelCatalogueUnavailable
from .catalogue_merge import Override, ProviderOverride
from .catalogue_model import (Catalogue, FieldName, ProviderFieldName, catalogue_from_json, catalogue_to_json,
                              field_value, provider_field_value)
from .catalogue_store import CatalogueStore

log = logging.getLogger("ashley.inference")
_FIELDS: frozenset[str] = frozenset(get_args(FieldName))
_PUT_FETCH = (
    "INSERT INTO model_catalogue_fetch (only_row, catalogue, fetched_at) VALUES (true, %s, %s) "
    "ON CONFLICT (only_row) DO UPDATE SET catalogue = excluded.catalogue, fetched_at = excluded.fetched_at")


@contextmanager
def translated() -> Generator[None]:
    """A database out of reach as ModelCatalogueUnavailable."""
    try:
        yield
    except DatabaseUnavailable as e:
        raise ModelCatalogueUnavailable("no database connection") from e
    except psycopg.OperationalError as e:
        raise ModelCatalogueUnavailable("database unreachable") from e


class PostgresCatalogue(CatalogueStore):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def fetched_at(self) -> datetime | None:
        with translated():
            async with self._database.connection() as conn:
                row = await (await conn.execute("SELECT fetched_at FROM model_catalogue_fetch")).fetchone()
        return None if row is None else row[0]

    async def fetched(self) -> tuple[Catalogue, datetime] | None:
        with translated():
            async with self._database.connection() as conn:
                row = await (await conn.execute("SELECT catalogue, fetched_at FROM model_catalogue_fetch")).fetchone()
        if row is None:
            return None
        try:
            return await asyncio.to_thread(catalogue_from_json, row[0]), row[1]
        except ValueError:
            logs.error(log, "catalogue.fetch_unreadable", exc=True)
            return None

    async def put_fetch(self, catalogue: Catalogue, at: datetime) -> None:
        with translated():
            async with self._database.connection() as conn:
                await conn.execute(_PUT_FETCH, (Jsonb(catalogue_to_json(catalogue)), at))

    async def overrides(self) -> list[Override]:
        with translated():
            async with self._database.connection() as conn:
                rows = await (await conn.execute(
                    "SELECT provider, model, field, value, person_id, set_at FROM model_catalogue_overrides")).fetchall()
        found: list[Override] = []
        for provider, model, field, value, person, at in rows:
            held = _held(str(field), value)
            if held is None:
                logs.warning(log, "catalogue.override_dropped", provider=provider, model=model, field=field)
                continue
            found.append(Override(str(provider), str(model), held[0], held[1], person, at))
        return found

    async def provider_overrides(self) -> list[ProviderOverride]:
        with translated():
            async with self._database.connection() as conn:
                rows = await (await conn.execute(
                    "SELECT provider, field, value, person_id, set_at FROM model_catalogue_provider_overrides")).fetchall()
        found: list[ProviderOverride] = []
        for provider, field, value, person, at in rows:
            name = _provider_field(str(field))
            held = None if name is None else _held_provider(name, value)
            if name is None or held is None:
                logs.warning(log, "catalogue.override_dropped", provider=provider, field=field)
                continue
            found.append(ProviderOverride(str(provider), name, held, person, at))
        return found


def _provider_field(field: str) -> ProviderFieldName | None:
    return next(iter(f for f in get_args(ProviderFieldName) if f == field), None)


def _held_provider(field: ProviderFieldName, value: object) -> str | None:
    try:
        return provider_field_value(field, value)
    except ValueError:
        return None


def _held(field: str, value: object) -> tuple[FieldName, object] | None:
    """A stored field and its value as held, None when the code no longer knows the field or refuses its value."""
    if field not in _FIELDS:
        return None
    name: FieldName = next(f for f in get_args(FieldName) if f == field)
    try:
        return name, field_value(name, value)
    except ValueError:
        return None
