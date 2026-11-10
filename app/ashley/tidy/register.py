"""How Tidy is wired."""

from .. import services
from ..db.database import Database
from .postgres import PostgresTidy
from .tidy import Tidy


def register(database: Database) -> None:
    """Make `PostgresTidy` over `database` the answer to `services.get(Tidy)`."""
    services.register(Tidy, PostgresTidy(database))
