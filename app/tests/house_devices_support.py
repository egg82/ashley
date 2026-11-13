"""The household's devices as a fake `Devices` lists them: `rows` by household."""

from dataclasses import dataclass, field

from ashley.channels.devices import Devices
from ashley.channels.model import Device, DiscordServer, Listed, Satellite


@dataclass
class HouseDevices(Devices):
    """The household's devices as `of_household` lists them: `rows` by household."""

    rows: dict[int, list[Listed]] = field(default_factory=dict[int, list[Listed]])

    async def by_token(self, token: str) -> Device | None:
        return None

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return self.rows.get(household_id, [])
