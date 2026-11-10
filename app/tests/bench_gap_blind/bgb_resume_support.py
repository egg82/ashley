"""A turn another pod resumes through `channels.resume.sweep`: a checkpoint of a bench talk's turn, handed over as an
orphan by an in-memory `InFlight`, over the fakes `respond_support.wired` registers."""

from dataclasses import replace

from ashley import services
from ashley.channels import resume
from ashley.channels.checkpoint import Checkpoint, dumps
from ashley.channels.tool_loop import Progress
from ashley.conversations.inflight import Claim, InFlight, Orphan
from ashley.conversations.model import NewTurn
from ashley.inference.model import Message, SystemPrompt, ToolResult, ToolResults
from bgb_support import Keeping, one
from respond_support import ALANA, HOME, Fakes, inbound

ASK = "let's see it"
BENCH = replace(inbound(thread="bench:4", speaker_id=ALANA.id, kind="brainstorm"), audience="owner", shared=False,
                place=None, channel="web", bench_id=4, later=True, later_by="turn")


class Orphans(Keeping):
    """Hands `found` to the first sweep."""

    def __init__(self, found: list[Orphan]) -> None:
        super().__init__()
        self.found = found

    async def orphaned(self, limit: int) -> list[Orphan]:
        got, self.found = self.found, []
        return got


def after_a_call() -> Progress:
    """A turn with one round done: its call and the result."""
    return Progress((Message("person", ASK), one(0), ToolResults((ToolResult("r0c0", "ok"),))), 1, 1)


async def resumed(wired: Fakes, *, worked_s: float, age_s: float, windows: int = 0,
                  progress: Progress | None = None) -> int:
    """Sweep once over a bench-talk turn checkpointed with `worked_s` and `windows`, stored `age_s` ago."""
    conv = await wired.conversations.for_thread(HOME.id, "bench:4", "brainstorm", [ALANA.id])
    said = await wired.conversations.add_turn(conv.id, NewTurn("person", ASK, ALANA.id))
    start = progress if progress is not None else Progress((Message("person", ASK),), 0, 0)
    saved = Checkpoint(BENCH, conv.id, said.id, ALANA.id, {"default": SystemPrompt("system", "moment")}, start,
                       worked_s=worked_s, windows=windows)
    orphan = Orphan(Claim(said.id, conv.id, "h"), dumps(saved), 1, age_s)
    services.register(InFlight, Orphans([orphan]))
    return await resume.sweep()
