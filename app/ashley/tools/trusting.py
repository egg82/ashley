"""A `Tools` for a turn nobody asked for, in front of the turn's own and behind `outside.Outside` (`decisions.md`, "What
she may just do is a person's setting over the floor"): a call of a kind its person set to offer first (`trust.kinds`)
is tier `asks`, so `Outside` holds it as a proposal by its one hold path. Any other call has the tier the source gives,
so this only ever raises a tier, never lowers one: a kind with a `floor` is left to the floor, and `act` changes
nothing. The person's choices are read once, on the first call that needs them; choices that cannot be read are
offer first for every kind. Logs `trust.offered` (tool, kind) and `trust.unreadable` (household, person), never
arguments."""

import logging
from collections.abc import Mapping, Sequence

from .. import logs, services
from ..inference.model import Tier, ToolCall, ToolResult
from ..trust.kinds import Kinds, Value, load
from ..trust.trust import Trust, TrustUnavailable
from .action_judge import Vetting
from .tools import Catalogue, Tools

log = logging.getLogger("ashley.tools")
_KINDS = load()


class Trusting(Tools):
    def __init__(self, source: Tools, household_id: int, person_id: int, kinds: Kinds | None = None) -> None:
        """`person_id` is the person the turn is for, whose choices decide."""
        self._source, self._household_id, self._person_id = source, household_id, person_id
        self._kinds = kinds or _KINDS
        self._values: Mapping[str, Value] | None = None

    async def catalogue(self) -> Catalogue:
        return await self._source.catalogue()

    async def call(self, call: ToolCall) -> ToolResult:
        return await self._source.call(call)

    async def tier(self, call: ToolCall) -> Tier | None:
        """`asks` for a call of a kind with no floor that its person set to offer first, or whose choices cannot be read;
        else the source's tier."""
        floor = await self._source.tier(call)
        kind = self._kinds.of(call.name, call.arguments)
        if kind is None or kind.floor is not None or (await self._chosen()).get(kind.kind, "offer") == "act":
            return floor
        logs.info(log, "trust.offered", tool=call.name, kind=kind.kind)
        return "asks"

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        return await self._source.vetted(call, words)

    async def shown(self, call: ToolCall) -> str | None:
        return await self._source.shown(call)

    async def _chosen(self) -> Mapping[str, Value]:
        if self._values is None:
            try:
                stored = await services.get(Trust).stored(self._household_id, self._person_id)
                self._values = self._kinds.effective(stored.values)
            except TrustUnavailable:
                logs.warning(log, "trust.unreadable", household=self._household_id, person=self._person_id)
                self._values = {}
        return self._values
