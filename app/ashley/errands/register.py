"""How Errands and BenchJobs are wired: the Postgres stores."""

from .. import services
from ..db.database import Database
from .bench_jobs import BenchJobs
from .bench_jobs_postgres import PostgresBenchJobs
from .errands import Errands
from .postgres import PostgresErrands


def register(database: Database) -> None:
    """Register the Postgres stores of errands and bench jobs on `database`."""
    services.register(Errands, PostgresErrands(database))
    services.register(BenchJobs, PostgresBenchJobs(database))
