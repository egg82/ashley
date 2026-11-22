"""What makes the reach eval safe: `ReachGuard` wraps the whole of a turn's tools (`channels.turn_tools.for_turn`), every
source at once, so a call reaches the service behind it only when the spec a catalogue offered for it says it only reads
(`ToolSpec.reads`), whichever catalogue offered it (a group the loader brings in appears in a later one); any other call
is noted in `refused` and answered as done. It also keeps which source offered each tool (`offered`), so a call can be
scored by its group whatever the run's variant cuts from what the model sees."""

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..inference.model import Tier, ToolCall
from ..tools.action_judge import Vetting
from ..tools.tools import Catalogue
from .house_guard import Attempt, GuardedTools
from .prompt_sizes import UNOWNED


@dataclass
class Notes:
    """What every guard of a run notes, shared since a turn builds its tools again when its page moves: the calls kept
    from their services (`refused`), the group of each tool a catalogue held, by name (`offered`), and the names whose
    spec said it only reads (`reads`), from every catalogue a guard was asked for."""

    refused: list[Attempt] = field(default_factory=list[Attempt])
    offered: dict[str, str] = field(default_factory=dict[str, str])
    reads: set[str] = field(default_factory=set[str])


@dataclass
class ReachGuard(GuardedTools):
    """`GuardedTools` over a turn's tools, noting into `notes`, that lets through the names `notes.reads` holds. The
    tier, vetting and shown line of a call are the turn's own, so a held change is held as it is in the app."""

    reads: set[str] = field(init=False)
    notes: Notes = field(default_factory=Notes)

    def __post_init__(self) -> None:
        self.refused = self.notes.refused
        self.reads = self.notes.reads

    async def catalogue(self) -> Catalogue:
        got = await super().catalogue()
        self.notes.offered.update({s.name: got.owners.get(s.name, UNOWNED) for s in got.specs})
        return got

    async def tier(self, call: ToolCall) -> Tier | None:
        return await self.inner.tier(call)

    async def vetted(self, call: ToolCall, words: Sequence[str]) -> Vetting | None:
        return await self.inner.vetted(call, words)

    async def shown(self, call: ToolCall) -> str | None:
        return await self.inner.shown(call)
