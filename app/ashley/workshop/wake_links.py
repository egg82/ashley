"""Which installed automation sends the event a wake rule answers, and which installed automation sends an event no
wake rule answers (`decisions.md`, "Home Assistant wakes her; she decides"), read for a bench's pieces.

An automation sends what its latest `done` install wrote to the house (`Installs.wake_installs`), not what its piece
says now, and is named only while its piece is on the layout of an open bench. A rule answers an event when any piece
on an open bench of the household holds a rule for it (`wake_rule.rule_of`), whatever `who` and `what` it is keyed on:
whether it answers one particular wake is `ashley.channels.wake.rule`'s call. Another member's automation is counted
but never named, since a bench is its owner's."""

from collections.abc import Mapping
from dataclasses import dataclass

from .. import services
from .installs import Installs
from .model import Owner
from .wake_rule import rule_of
from .workshop import Workshop

RULE_KIND = "wake"
AUTOMATION_KIND = "automation"


@dataclass(frozen=True)
class Sender:
    """An installed automation piece that sends an event; `title` is None when it is on another member's bench."""

    bench_id: int
    piece_id: int
    title: str | None


@dataclass(frozen=True)
class WakeLinks:
    answered: frozenset[str]
    senders: Mapping[str, tuple[Sender, ...]]

    def senders_of(self, event: str) -> tuple[Sender, ...]:
        return self.senders.get(event, ())

    def unanswered(self, events: tuple[str, ...]) -> tuple[str, ...]:
        """`events` that no wake rule on an open bench answers, once each, in order."""
        return tuple(dict.fromkeys(e for e in events if e not in self.answered))


async def links_of(owner: Owner) -> WakeLinks:
    """Raises WorkshopUnavailable and InstallsUnavailable."""
    rules = await services.get(Workshop).of_kind(owner.household_id, RULE_KIND)
    answered = frozenset(r.event for p in rules if (r := rule_of(p.body)) is not None)
    installed = await services.get(Installs).wake_installs(owner.household_id)
    placed = {(p.bench_id, p.piece_id): p for p in await services.get(Workshop).of_kind(owner.household_id, AUTOMATION_KIND)}
    senders: dict[str, list[Sender]] = {}
    for found in installed:
        piece = placed.get((found.bench_id, found.piece_id))
        if piece is None:
            continue
        sender = Sender(piece.bench_id, piece.piece_id, piece.title if piece.owner_id == owner.person_id else None)
        for event in dict.fromkeys(found.events):
            senders.setdefault(event, []).append(sender)
    return WakeLinks(answered, {e: tuple(s) for e, s in senders.items()})

