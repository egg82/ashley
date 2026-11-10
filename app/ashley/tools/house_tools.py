"""Her tools over a household's house (`home_assistant.house.House`), offered to every turn: `house_state` (the live
state of the devices the household lists for her), `house_find` (anything the house has and how it is set up),
`house_history` (how things changed), `house_ask` (an action that only reads) and `house_do` (any other action). The
guidance is her own, `home_assistant.md`, then the devices the household lists, one line per area, read from the house
when the catalogue is fetched and kept for `catalogue_ttl_s`. Changes to the house's configuration and the ones that
need a person's OK are `house_change` (`house_change`), which needs a known speaker.

Arguments and results can carry people's data and are never logged; the `tools.call` line carries the tool, the outcome
and the tool's own counts and kinds."""

import copy
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from .. import logs
from ..home_assistant.house import House, HouseRejected, HouseUnavailable
from ..home_assistant.house_values import HouseValues
from ..inference.model import Tier, ToolCall, ToolResult, ToolSpec
from . import house_act, house_find, house_history, house_tier, house_vet
from .action_judge import Vetting
from .house_answer import Answer
from .house_look_config import HouseLookConfig
from .house_roster import devices, roster
from .house_state import SPEC as STATE_SPEC, HouseStateTools
from .house_state_config import HouseStateConfig
from .house_targets import entity_of
from .tiers import CONFIG as TIERS
from .tiers_config import TiersConfig
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")
STATE = STATE_SPEC.name


@dataclass
class _Cached:
    """The catalogue as built, with when it stops being served; shared by the copies `for_turn` makes."""

    until: float = 0.0
    value: Catalogue | None = None


class HouseTools(Tools):
    def __init__(self, house: House, rules: house_act.Rules, look: HouseLookConfig, state: HouseStateConfig,
                 guidance: str = "", household_id: int = 0, tiers: TiersConfig = TIERS,
                 consequential: tuple[str, ...] = (),
                 values: Callable[[], Awaitable[HouseValues]] | None = None) -> None:
        """`rules`, `tiers` and `consequential` are the rules as given; `values` reads the household's own settings
        (`home_assistant.house_values`), which `for_turn` applies once per turn in their place."""
        self._house = house
        self._tiers = tiers
        self._household_id = household_id
        self._rules = rules
        self._consequential = consequential
        self._values = values
        self._look = look
        self._state = HouseStateTools(house, state)
        self._guidance = guidance
        self._cache = _Cached()

    async def for_turn(self) -> Tools:
        """These tools with the household's settings as they are now, read once: one turn never sees two versions."""
        if self._values is None:
            return self
        values = await self._values()
        turn = copy.copy(self)
        turn._rules = self._rules.for_household(values)
        turn._consequential = values.consequential
        turn._values = None
        return turn

    async def catalogue(self) -> Catalogue:
        started = time.monotonic()
        if self._cache.value is not None and started < self._cache.until:
            logs.info(log, "tools.catalogue", count=len(self._cache.value.specs), cached=True, duration_ms=0)
            return self._cache.value
        try:
            states = await self._house.states()
        except HouseUnavailable as e:
            logs.warning(log, "tools.unavailable", reason=str(e).split(":")[0], duration_ms=_ms(started))
            raise ToolsUnavailable("the house did not answer") from e
        specs: tuple[ToolSpec, ...] = (STATE_SPEC, house_find.SPEC, house_history.SPEC, house_act.ASK_SPEC,
                                       house_act.DO_SPEC)
        listed = tuple(entity_of(s) for s in states if s.featured)
        built = Catalogue(specs, "\n\n".join(t for t in (self._guidance, roster(listed), await self._devices()) if t))
        self._cache.until, self._cache.value = time.monotonic() + self._look.catalogue_ttl_s, built
        logs.info(log, "tools.catalogue", count=len(specs), cached=False, duration_ms=_ms(started))
        return built

    async def tier(self, call: ToolCall) -> Tier | None:
        """`house_do`'s from what it names (`house_tier`); another tool's as `Tools.tier` gives it."""
        if call.name == house_act.DO:
            return await house_tier.of_call(self._house, call.arguments, self._tiers, self._consequential)
        return await super().tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        """`house_do`'s view, from the things it names (`house_vet`); None for another tool."""
        if call.name != house_act.DO:
            return None
        return Vetting(view=await house_vet.view_of(self._house, call.arguments))

    _offered = frozenset({house_find.NAME, house_history.NAME, house_act.ASK, house_act.DO})

    async def _run(self, name: str, arguments: Mapping[str, object]) -> Answer:
        if name == house_find.NAME:
            return await house_find.run(self._house, arguments, self._look)
        if name == house_history.NAME:
            return await house_history.run(self._house, arguments, self._look)
        return await house_act.run(self._house, name, arguments, self._rules, self._look, self._household_id)

    async def _devices(self) -> str:
        """The line of the house's devices for her instructions, empty when the registry cannot be read: the roster of
        entities stands without it."""
        try:
            line = devices(await self._house.records("device"), self._look.devices_chars)
        except HouseUnavailable:
            return ""
        return f"Devices in the house (house_find kind device says more of each): {line}" if line else ""

    async def call(self, call: ToolCall) -> ToolResult:
        started = time.monotonic()
        if call.name == STATE:
            return await self._state.call(call)
        if call.name not in self._offered:
            return _done(call, "unknown_tool", started, ToolResult(call.id, f"no tool named {call.name}", True))
        try:
            answer = await self._run(call.name, call.arguments)
        except ValueError as e:
            return _done(call, "bad_arguments", started, ToolResult(call.id, str(e), True))
        except HouseRejected as e:
            return _done(call, "error", started, ToolResult(call.id, f"the house refused it: {e.message}", True))
        except HouseUnavailable as e:
            return _done(call, "unavailable", started, ToolResult(call.id, "the house did not answer", True),
                         reason=str(e).split(":")[0])
        return _done(call, "error" if answer.is_error else "ok", started, ToolResult(call.id, answer.text, answer.is_error, outside=answer.outside),
                     **answer.fields)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _done(call: ToolCall, outcome: str, started: float, result: ToolResult, **fields: str | int | bool) -> ToolResult:
    logs.info(log, "tools.call", **{**fields, "tool": call.name, "outcome": outcome, "duration_ms": _ms(started)})
    return result
