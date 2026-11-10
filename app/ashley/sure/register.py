"""How Sure is wired: its HTTP port and the household's Ledger over it."""

import httpx2

from .. import services
from ..ledger.ledger import Ledger
from .client import HttpSure, Sure
from .ledger import SureLedger


def register(http: httpx2.AsyncClient, timeout_s: float) -> None:
    """Register Sure's port on `http`, which must not follow redirects, and the Ledger that reads through it."""
    services.register(Sure, HttpSure(http, timeout_s))
    services.register(Ledger, SureLedger())
