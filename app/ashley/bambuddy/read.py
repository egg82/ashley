"""How the adapters read Bambuddy for a household: its connection opened by port, one GET parsed into a wire shape, the
connection's `checked_at` moved when it answered. Failures leave as the caller's own exception, built by `fail`."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Literal

from pydantic import BaseModel

from .. import services
from ..connections import answered, ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..connections.model import Opened, Port
from . import wire
from .client import Bambuddy, BambuddyFailed, Fetched, Reason


Turned = Literal["not_found", "rejected"]
"""A write Bambuddy turned away: the record it names is not there, or it would not accept what was sent."""


class Reader:
    """Reads and writes for one port: `unavailable`, `not_connected` and `failed` build the port's own exceptions."""

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

    async def fetch(self, opened: Opened, path: str, params: Mapping[str, str | int | bool]) -> Fetched | None:
        """The picture Bambuddy answers at `path`, None for a 404. Raises the port's failure."""
        try:
            got = await services.get(Bambuddy).fetch(opened.connection.base_url, opened.secret, path, params)
        except BambuddyFailed as e:
            if e.reason == "not_found":
                return None
            raise self._failed(e.reason) from e
        await answered.record(opened.connection.id)
        return got

    async def post[M: BaseModel](self, opened: Opened, path: str, body: Mapping[str, object],
                                 model: type[M]) -> M | Turned:
        """What Bambuddy answers a JSON POST at `path`; `not_found` or `rejected` when it turned the write away so.
        Raises the port's failure."""
        connection, secret = opened.connection, opened.secret
        return await self._written(opened, model,
                                   services.get(Bambuddy).post(connection.base_url, secret, path, body))

    async def upload[M: BaseModel](self, opened: Opened, path: str, name: str, data: bytes,
                                   model: type[M]) -> M | Turned:
        """As `post`, for the file `name` of `data` sent as a multipart upload."""
        connection, secret = opened.connection, opened.secret
        return await self._written(opened, model, services.get(Bambuddy).upload(connection.base_url, secret, path, name,
                                                                                 data))

    async def _written[M: BaseModel](self, opened: Opened, model: type[M],
                                     sent: Awaitable[object]) -> M | Turned:
        try:
            got = wire.parsed(model, await sent)
        except BambuddyFailed as e:
            if e.reason in ("not_found", "rejected"):
                return e.reason
            raise self._failed(e.reason) from e
        await answered.record(opened.connection.id)
        return got

    async def need(self, household_id: int) -> Opened:
        opened = await self.opened(household_id)
        if opened is None:
            raise self._not_connected()
        return opened
