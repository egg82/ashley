"""The Everyday service (`ashley.services`): the tools every turn of a household shares. A household with a Home
Assistant (`ashley.home_assistant.homes.Homes`) gets the tools built over its own house, kept while its Home is the
same, since their catalogue is cached; one without gets the locator's `Tools`, which reach no house, or, when
`without_house` is given, that household's own, kept the same way (the look-up with places near its own location).
`HouseholdTools` is the Proxy a turn holds: it asks for its household's tools once, on first use."""

from abc import abstractmethod
from collections.abc import Callable, Sequence

from .. import services
from ..home_assistant.homes import Home, Homes, HomesUnavailable
from ..inference.model import Tier, ToolCall, ToolResult
from ..services import Service
from .action_judge import Vetting
from .tools import Catalogue, Tools, ToolsUnavailable


class Everyday(Service):
    @classmethod
    def null(cls) -> "Everyday":
        return NullEveryday()

    @abstractmethod
    async def of(self, household_id: int) -> Tools:
        """The household's everyday tools. Raises ToolsUnavailable when which house it has cannot be read now."""


class NullEveryday(Everyday):
    """Every household gets the locator's `Tools`."""

    async def of(self, household_id: int) -> Tools:
        return services.get(Tools)


class HomesEveryday(Everyday):
    def __init__(self, build: Callable[[Home], Tools], without_house: Callable[[int], Tools] | None = None) -> None:
        """`build` makes the everyday tools over one household's Home; `without_house` those of a household with none."""
        self._build = build
        self._without_house = without_house
        self._built: dict[int, tuple[Home, Tools]] = {}
        self._bare: dict[int, Tools] = {}

    async def of(self, household_id: int) -> Tools:
        try:
            home = await services.get(Homes).of(household_id)
        except HomesUnavailable as e:
            raise ToolsUnavailable("the household's house could not be read") from e
        if home is None:
            self._built.pop(household_id, None)
            if self._without_house is None:
                return services.get(Tools)
            if household_id not in self._bare:
                self._bare[household_id] = self._without_house(household_id)
            return self._bare[household_id]
        self._bare.pop(household_id, None)
        built = self._built.get(household_id)
        if built is None or built[0] is not home:
            built = (home, self._build(home))
            self._built[household_id] = built
        return built[1]


class HouseholdTools(Tools):
    """One household's everyday tools for one turn."""

    def __init__(self, household_id: int) -> None:
        self._household_id = household_id
        self._tools: Tools | None = None

    async def catalogue(self) -> Catalogue:
        return await (await self._resolved()).catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        try:
            tools = await self._resolved()
        except ToolsUnavailable:
            return ToolResult(call.id, "the house did not answer", is_error=True)
        return await tools.call(call)

    async def _resolved(self) -> Tools:
        if self._tools is None:
            self._tools = await (await services.get(Everyday).of(self._household_id)).for_turn()
        return self._tools

    async def tier(self, call: ToolCall) -> Tier | None:
        try:
            return await (await self._resolved()).tier(call)
        except ToolsUnavailable:
            return await super().tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        try:
            return await (await self._resolved()).vetted(call, words)
        except ToolsUnavailable:
            return None
