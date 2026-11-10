"""Alembic's environment. The connection string comes from `ashley.db.migrate`, which holds the advisory lock around
the whole upgrade; the engine hands alembic libpq connections made from it verbatim, so a multi-host string works."""

import psycopg
from alembic import context
from sqlalchemy import create_engine

conninfo: str = context.config.attributes["conninfo"]
engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(conninfo))

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
