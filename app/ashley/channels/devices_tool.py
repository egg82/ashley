"""Her read of the household's own devices (`household_devices`): the satellites, tablets, Discord servers and the
house she runs on, from the Devices service, so "how many Echos are there" is a lookup. Not Home Assistant's entities
(`house_state`, the house roster): those are what the house offers, these are the machines she is reached through.
Offered on every turn of a known speaker. Carries no token, host or server id; `tools.call` logs the row count."""

import time

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..tools import bench_results
from ..tools.tools import Catalogue, Tools
from .devices import Devices, DevicesUnavailable

NAME = "household_devices"
SPEC = ToolSpec(NAME, "List the devices this household reaches you through: each one's id, name, place, what it is "
                "(satellite: a voice satellite; discord_server; house: the household's Home Assistant; other: a "
                "tablet or the like), who hears it (audience) and whether it speaks or shows text (medium). Use "
                "it to count or name them. Their hardware and firmware are not here; a device's setup may be in "
                "the code host.", {"type": "object", "properties": {}}, reads=True, outside=False)


class DeviceTools(Tools):
    def __init__(self, household_id: int) -> None:
        self._household = household_id

    async def catalogue(self) -> Catalogue:
        return Catalogue((SPEC,), None)

    async def call(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        if call.name != NAME or call.arguments:
            return bench_results.failed(call, started, "unknown_tool" if call.name != NAME else "bad_arguments",
                                        f"no tool named {call.name}" if call.name != NAME else f"{NAME} takes no arguments")
        try:
            found = await services.get(Devices).of_household(self._household)
        except DevicesUnavailable:
            return bench_results.failed(call, started, "unavailable", "the devices cannot be read right now")
        rows = [{"id": d.device.id, "name": d.device.name, "place": d.device.place, "form": d.form,
                 "audience": d.device.audience, "medium": d.device.medium, "kind": d.device.kind} for d in found]
        return bench_results.ok(call, started, {"devices": rows, "count": len(rows)}, rows=len(rows))
