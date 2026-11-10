"""How Proposals and the outside record are wired: the Postgres stores."""

from .. import services
from ..db.database import Database
from .outside_record import OutsideRecord
from .postgres_outside_record import PostgresOutsideRecord
from .postgres_proposals import PostgresProposals
from .proposals import Proposals


def register(database: Database, actions_keep_s: float, writes_keep_s: float) -> None:
    """Register the Postgres stores of proposals and of what a tainted turn did on its own, which keeps its actions and its
    list writes for the seconds given."""
    services.register(Proposals, PostgresProposals(database))
    services.register(OutsideRecord, PostgresOutsideRecord(database, actions_keep_s, writes_keep_s))
