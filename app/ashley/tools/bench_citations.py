"""The turn a measurements choice row of hers cites, checked by her bench tools before her Add or Edit reaches the
Workshop: a row she adds or changes as `stated` or `accepted` names a person's turn on the talk this turn is in
(`measurements.cited_turns`). The talk is the tool's, not the bench's, so `decide` cannot check it; it checks a cited
piece itself."""

from collections.abc import Awaitable, Callable

from .. import services
from ..workshop import measurements
from ..workshop.commands import Add, Edit
from ..workshop.model import Owner
from ..workshop.rules import Rules
from ..workshop.workshop import Workshop
from .bench_reference import Refused, SaidUnavailable
from .bench_results import HINTS

PeopleTurns = Callable[[], Awaitable[frozenset[int]]]
"""Reads the ids of the people's turns in this conversation (`channels.said_links.turns_by_people`); raises
SaidUnavailable when it cannot be read."""


class Citations:
    def __init__(self, owner: Owner, bench_id: int, rules: Rules, turns: PeopleTurns | None) -> None:
        self._owner = owner
        self._bench = bench_id
        self._rules = rules
        self._turns = turns

    async def check(self, command: Add | Edit) -> None:
        """Raises Refused `bad_citation` when `command` adds or changes a choice row citing a turn that is missing or is
        not a person's turn on this talk (none is, with no talk), and `unavailable` when the talk cannot be read. The
        bench is read only for a body holding such a row."""
        body = command.text.body
        if not measurements.cited_turns("", body):
            return
        before = await self._before(command)
        if before is None:
            return
        cited = measurements.cited_turns(before, body)
        if not cited:
            return
        said = await self._said()
        if any(turn is None or turn not in said for turn in cited):
            raise Refused("bad_citation", HINTS["bad_citation"])

    async def _before(self, command: Add | Edit) -> str | None:
        """The body the command changes ("" for an Add); None when its piece is not a measurements piece."""
        if isinstance(command, Add):
            return "" if self._is_measurements(command.kind) else None
        view = await services.get(Workshop).read(self._owner, self._bench)
        found = next((p for p in view.pieces if p.id == command.piece_id), None)
        return found.text.body if found is not None and self._is_measurements(found.kind) else None

    def _is_measurements(self, kind_name: str) -> bool:
        kind = self._rules.kinds.get(kind_name)
        return kind is not None and kind.format == "measurements"

    async def _said(self) -> frozenset[int]:
        if self._turns is None:
            return frozenset()
        try:
            return await self._turns()
        except SaidUnavailable as e:
            raise Refused("unavailable", "the conversation cannot be read right now, so a cited turn cannot be checked") from e
