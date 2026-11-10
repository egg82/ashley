"""Helpers for the blind `POST /api/messages` tests: a fake Devices with two signed-in devices, and an app client with
every system the turn loop reaches swapped for the `turns_support` fakes after the factory wired the real ones."""

from collections.abc import Generator
from contextlib import contextmanager

from ashley import services
from ashley.channels.devices import Devices
from ashley.channels.model import Device, DiscordServer, Listed, Satellite
from contract_support import client, unreachable_conninfo
from fastapi.testclient import TestClient
from turns_support import HOUSE, World, register

TOKEN = "zqTOK-spoken-1f2e3d"  # gitleaks:allow (test fixture)
TEXT_TOKEN = "zqTOK-text-9a8b7c"
SPOKEN_DEVICE = Device(7, HOUSE, "kitchen satellite", "kitchen", "present", "spoken", "command")
TEXT_DEVICE = Device(8, HOUSE, "hallway tablet", "hallway", "household", "text", "chat")


class FakeDevices(Devices):
    def __init__(self) -> None:
        self.by = {TOKEN: SPOKEN_DEVICE, TEXT_TOKEN: TEXT_DEVICE}
        self.asked: list[str] = []
        self.error: Exception | None = None

    async def by_token(self, token: str) -> Device | None:
        self.asked.append(token)
        if self.error:
            raise self.error
        return self.by.get(token)

    async def allow(self, device_id: int) -> bool:
        return True

    async def satellites(self) -> list[Satellite]:
        return []

    async def discord_servers(self) -> list[DiscordServer]:
        return []

    async def of_household(self, household_id: int) -> list[Listed]:
        return []


def bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def app(world: World, devices: FakeDevices | None) -> Generator[TestClient]:
    """The app over fakes; `devices` None leaves Devices unwired, its Null Object answering."""
    with client(unreachable_conninfo()) as c:
        register(world)
        if devices is None:
            services.unregister(Devices)
        else:
            services.register(Devices, devices)
        try:
            yield c
        finally:
            services.unregister(Devices)
