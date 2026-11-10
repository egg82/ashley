"""How Watches is wired: the Postgres store."""

from .. import services
from ..db.database import Database
from .postgres import PostgresWatches
from .watches import Watches


def register(database: Database) -> None:
    """Register the Postgres store of watches on `database`."""
    services.register(Watches, PostgresWatches(database))
