"""How the adapters read Bambuddy for a household: its connection opened by port, one GET parsed into a wire shape, the
connection's `checked_at` moved when it answered. Failures leave as the caller's own exception, built by `fail`."""

from collections.abc import Callable, Mapping
from pydantic import BaseModel

from .. import services
from ..connections import answered, ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened, Port
from . import wire
from .client import Bambuddy, BambuddyFailed, Reason


class Reader:
    """Reads for one port: `unavailable`, `not_connected` and `failed` build the port's own exceptions."""

    def __init__(self, port: Port, unavailable: Callable[[], Exception], not_connected: Callable[[], Exception],
                 failed: Callable[[Reason], Exception]) -> None:
        self._port: Port = port
        self._unavailable = unavailable
        self._not_connected = not_connected
        self._failed = failed

    async def opened(self, household_id: int) -> Opened | None:
        try:
            return await ports.opened(services.get(Connections), self._port, household_id)
        except ConnectionsUnavailable as e:
            raise self._unavailable() from e

    async def get[M: BaseModel](self, opened: Opened, path: str, params: Mapping[str, str | int | bool],
                                model: type[M]) -> M | None:
        """What Bambuddy answers at `path`, None for a 404. Raises the port's failure."""
        try:
            got = wire.parsed(model, await services.get(Bambuddy).get(opened.connection.base_url, opened.secret, path,
                                                                      params))
        except BambuddyFailed as e:
            if e.reason == "not_found":
                return None
            raise self._failed(e.reason) from e
        await answered.record(opened.connection.id)
        return got

    async def need(self, household_id: int) -> Opened:
        opened = await self.opened(household_id)
        if opened is None:
            raise self._not_connected()
        return opened
