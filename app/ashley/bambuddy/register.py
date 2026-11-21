"""How Bambuddy is wired: its HTTP port and the household's Printing and Stock over it. Its camera source
(`cameras.BambuddyCameras`) joins the others in `ashley.wiring_cameras`."""

import httpx2

from .. import services
from ..printing.printing import Printing
from ..stock.stock import Stock
from .client import Bambuddy, HttpBambuddy
from .printing import BambuddyPrinting
from .stock import BambuddyStock


def register(http: httpx2.AsyncClient, timeout_s: float, upload_timeout_s: float) -> None:
    """Register Bambuddy's port on `http`, which must not follow redirects, and the services that read through it."""
    services.register(Bambuddy, HttpBambuddy(http, timeout_s, upload_timeout_s))
    services.register(Printing, BambuddyPrinting())
    services.register(Stock, BambuddyStock())
