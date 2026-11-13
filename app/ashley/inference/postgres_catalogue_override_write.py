"""A person's catalogue overrides written in Postgres, table `model_catalogue_overrides`: upserts and deletes in one
transaction. Contract: `catalogue_override_write`."""

import logging
from collections.abc import Collection, Mapping

from psycopg.types.json import Jsonb

from .. import logs
from ..db.database import Database
from .catalogue_model import FieldName, to_json
from .catalogue_override_write import CatalogueOverrideWriter
from .postgres_catalogue import translated

log = logging.getLogger("ashley.inference")
_PUT = (
    "INSERT INTO model_catalogue_overrides (provider, model, field, value, person_id) VALUES (%s, %s, %s, %s, %s) "
    "ON CONFLICT (provider, model, field) DO UPDATE SET value = excluded.value, person_id = excluded.person_id, "
    "set_at = now()")
_RESET = "DELETE FROM model_catalogue_overrides WHERE provider = %s AND model = %s AND field = ANY(%s)"


class PostgresCatalogueOverrideWriter(CatalogueOverrideWriter):
    def __init__(self, database: Database) -> None:
        self._database = database

    async def write(self, provider: str, model: str, put: Mapping[FieldName, object], reset: Collection[FieldName],
                    person_id: int) -> None:
        with translated():
            async with self._database.connection() as conn:
                if reset:
                    await conn.execute(_RESET, (provider, model, list(reset)))
                for field, value in put.items():
                    await conn.execute(_PUT, (provider, model, field, Jsonb(to_json(value)), person_id))
        logs.info(log, "catalogue.override_set", provider=provider, model=model, person=person_id, put=len(put),
                  reset=len(reset))
