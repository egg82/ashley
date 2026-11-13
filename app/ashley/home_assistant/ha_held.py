"""HeldStates over Home Assistant (`held_states.HeldStates`): while held, one `ha_held_socket.Socket` per household,
opened on the first ask and replaced when the household's connection changes; when not held, each thing read once over
REST. Which house is the household's comes from `Homes` on every ask. Tunables are data, `ha_held.json`."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from urllib.parse import quote

from .. import services
from .ha_held_socket import HeldSettings, Socket, state_of
from .ha_json import obj
from .ha_rest import Rest
from .held_states import EntityState, HeldStates
from .homes import Home, Homes
from .house_settings import HouseSettings, load as load_house

FILE = Path(__file__).with_name("ha_held.json")
_KEYS = ("backoff_s", "max_backoff_s", "idle_s", "ping_s")


def load() -> HeldSettings:
    """The tunables shipped in `ha_held.json`. Raises ValueError unless the keys are exactly `backoff_s`,
    `max_backoff_s` (at least `backoff_s`), `idle_s` and `ping_s`, each a number above 0."""
    raw = obj(json.loads(FILE.read_text()))
    if set(raw) != set(_KEYS):
        raise ValueError(f"ha_held.json has exactly {', '.join(_KEYS)}")
    numbers = [float(n) for n in (raw[k] for k in _KEYS) if isinstance(n, int | float) and not isinstance(n, bool)]
    if len(numbers) != len(_KEYS) or min(numbers) <= 0:
        raise ValueError("ha_held.json's values are numbers above 0")
    settings = HeldSettings(*numbers)
    if settings.max_backoff_s < settings.backoff_s:
        raise ValueError("ha_held.json's max_backoff_s is at least backoff_s")
    return settings


class SocketStates(HeldStates):
    def __init__(self, settings: HeldSettings | None = None, house: HouseSettings | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._settings = settings or load()
        self._house = house or load_house()
        self._sleep, self._clock = sleep, clock
        self._group: asyncio.TaskGroup | None = None
        self._sockets: dict[int, tuple[Socket, asyncio.Task[None]]] = {}
        self._changed: Callable[[], None] = _nothing

    async def hold(self, changed: Callable[[], None]) -> None:
        self._changed = changed
        try:
            async with asyncio.TaskGroup() as group:
                self._group = group
                await asyncio.Event().wait()
        finally:
            self._group = None
            self._sockets.clear()

    async def states(self, household_id: int, entity_ids: Sequence[str]) -> Mapping[str, EntityState | None] | None:
        home = await services.get(Homes).of(household_id)
        held = self._sockets.get(household_id)
        if held is not None and (home is None or held[0].home is not home):
            held[1].cancel()
            del self._sockets[household_id]
            held = None
        if home is None:
            return None
        if self._group is None:
            return await self._once(home, entity_ids)
        if held is None:
            socket = Socket(household_id, home, self._settings, self._house, self._told, self._sleep, self._clock)
            held = (socket, self._group.create_task(socket.run()))
            self._sockets[household_id] = held
        return await held[0].states(entity_ids)

    def _told(self) -> None:
        self._changed()

    async def _once(self, home: Home, entity_ids: Sequence[str]) -> Mapping[str, EntityState | None]:
        rest = Rest(home.home_assistant, self._house)
        return {e: state_of(e, await rest.get_or_none("/api/states/" + quote(e, safe=""), "state")) for e in entity_ids}


def _nothing() -> None:
    return None
