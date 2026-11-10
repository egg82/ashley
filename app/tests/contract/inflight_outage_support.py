"""An `InFlight` that fails as unreachable on demand, for the in-flight resume suites."""

from collections.abc import Callable
from dataclasses import dataclass

from ashley.conversations.inflight import Claim, InFlight, InFlightUnavailable, Orphan
from ashley.conversations.model import AgreedOutcome, NewTurn, Turn


@dataclass
class Outage(InFlight):
    """The real store until `down`; then every call fails as unreachable, as in a database switchover."""

    real: InFlight
    down: bool = False

    @property
    def claim_s(self) -> float:
        return self.real.claim_s

    def _up(self) -> None:
        if self.down:
            raise InFlightUnavailable("down")

    async def begin(self, conversation_id: int, said_id: int, checkpoint: str) -> Claim:
        self._up()
        return await self.real.begin(conversation_id, said_id, checkpoint)

    async def save(self, claim: Claim, checkpoint: str) -> None:
        self._up()
        await self.real.save(claim, checkpoint)

    async def renew(self, claim: Claim) -> None:
        self._up()
        await self.real.renew(claim)

    async def said(self, claim: Claim, turn: NewTurn) -> Turn:
        self._up()
        return await self.real.said(claim, turn)

    async def finish(self, claim: Claim, turn: NewTurn, after: Callable[[Turn], str] | None = None) -> Turn:
        self._up()
        return await self.real.finish(claim, turn, after)

    async def agreed(self, claim: Claim, outcome: AgreedOutcome) -> None:
        self._up()
        await self.real.agreed(claim, outcome)

    async def drop(self, claim: Claim) -> bool:
        self._up()
        return await self.real.drop(claim)

    async def orphaned(self, limit: int) -> list[Orphan]:
        self._up()
        return await self.real.orphaned(limit)

    async def working(self, conversation_id: int) -> frozenset[int]:
        self._up()
        return await self.real.working(conversation_id)
