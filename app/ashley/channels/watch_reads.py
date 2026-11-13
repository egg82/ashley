"""The tools a watch reads through (`ashley.watches.tool_reads.ToolReads`): the person's own tools as a turn for them
would offer them, narrowed to the ones that change nothing (`ToolSpec.reads`, enforced by `tools.reading.Reading`), so a
`tool` watch can run a read and never an action. Logs `watch_reads.refused` (tool name) for a name no read of theirs
has; never arguments or answers."""

import logging
from collections.abc import Mapping

from .. import logs
from ..inference.model import ToolCall
from ..tools.tools import ToolsUnavailable
from ..watches.model import ReadFailed
from ..watches.tool_reads import Text, ToolRead, ToolReads
from . import turn_tools
from .model import Inbound

log = logging.getLogger("ashley.channels.wake")


class ChannelToolReads(ToolReads):
    async def available(self, household_id: int, person_id: int) -> bool:
        return True

    async def read(self, household_id: int, person_id: int, tool: str, arguments: Mapping[str, object]) -> ToolRead:
        tools = turn_tools.for_turn(_inbound(household_id, person_id))
        try:
            if tool not in {s.name for s in (await tools.catalogue()).specs}:
                logs.warning(log, "watch_reads.refused", tool=tool)
                return ReadFailed("refused")
            result = await tools.call(ToolCall("watch", tool, arguments))
        except ToolsUnavailable:
            return ReadFailed("unreachable")
        return ReadFailed("bad_result") if result.is_error else Text(result.content)


def _inbound(household_id: int, person_id: int) -> Inbound:
    """A turn nobody waits on, for the person alone, with only the tools that read. No model reads what its tools
    return (the check hashes it), so nothing outside starts it; the wake's own turn carries the watch's taint."""
    return Inbound(household_id=household_id, thread=f"push:{person_id}", text="watch", kind="chat", medium="text",
                   audience="owner", speaker_id=person_id, shared=False, place=None, channel="device", remembers=False,
                   unprompted=True, author="household", reads_only=True, taint=None)
