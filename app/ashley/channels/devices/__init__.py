"""The Devices service (`ashley.services`): which device a sign-in token belongs to, which devices are voice
satellites, and which are households' Discord servers. A device's token is issued once by
`python -m ashley.channels.devices add` and only its SHA-256 is stored, so a database read never yields a usable
token. Callers import only this module and `model`; the Postgres implementation lives beside it.

Tokens are never logged, nor their hashes; device ids are."""

from abc import abstractmethod

from ...services import Service
from ..model import Device, DiscordServer, Listed, Satellite


class DevicesUnavailable(Exception):
    """The database could not be reached. Transient: the caller may retry."""


class Devices(Service):
    @classmethod
    def null(cls) -> "Devices":
        return NullDevices()

    @abstractmethod
    async def by_token(self, token: str) -> Device | None:
        """The device `token` signs in, None when it signs in none (unknown, revoked, or empty). Raises
        DevicesUnavailable."""

    @abstractmethod
    async def allow(self, device_id: int) -> bool:
        """Count one request by the device and say whether it is within its rate (`device_rate.json`), shared by every
        pod on either site. Over the rate it is False and still counted. Raises DevicesUnavailable."""

    @abstractmethod
    async def satellites(self) -> list[Satellite]:
        """Every unrevoked device with an ESPHome host, across all households, ordered by device id. One connection
        singleton holds them all, so it asks for all. Raises DevicesUnavailable."""

    @abstractmethod
    async def discord_servers(self) -> list[DiscordServer]:
        """Every unrevoked device with a Discord server, across households, ordered by device id. Raises
        DevicesUnavailable."""

    @abstractmethod
    async def of_household(self, household_id: int) -> list[Listed]:
        """The household's unrevoked devices, ordered by device id. Raises DevicesUnavailable."""


class NullDevices(Devices):
    """Signs in nothing: what an unwired process sees. Raises DevicesUnavailable, so a missing registration is a 503
    rather than every device being told its token is wrong."""

    async def by_token(self, token: str) -> Device | None:
        raise DevicesUnavailable("Devices is not wired")

    async def allow(self, device_id: int) -> bool:
        raise DevicesUnavailable("Devices is not wired")

    async def satellites(self) -> list[Satellite]:
        raise DevicesUnavailable("Devices is not wired")

    async def discord_servers(self) -> list[DiscordServer]:
        raise DevicesUnavailable("Devices is not wired")

    async def of_household(self, household_id: int) -> list[Listed]:
        raise DevicesUnavailable("Devices is not wired")
