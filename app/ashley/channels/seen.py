"""A turn that begins with her having looked at a camera's recording (`Inbound.seen`): the look is made by the same code as
her `camera_look` tool with its `recording` (`ashley.tools.camera_tools`), so the picture is prepared and kept as a look on
no bench exactly as when she asks for it, and the call and its result are entries of the turn before its first step. Because
they are entries of the checkpointed progress, a runner that takes the turn over has the picture too. A look that fails
(no still, the house unreachable, the turn's looks used up) is the tool's own error result, which tells her to say she
could not see. A turn that does not offer the tool begins without the look."""

from ..inference.model import Entry, ToolCall, ToolCalls, ToolResults, ToolSpec
from ..tools.camera_specs import LOOK
from ..tools.camera_tools import CameraTools
from .model import Inbound

CALL_ID = "seen"


async def carried(inbound: Inbound, conversation_id: int, said_id: int, entries: tuple[Entry, ...],
                  offered: tuple[ToolSpec, ...]) -> tuple[Entry, ...]:
    """`entries`, followed by the look `inbound.seen` names as her tool call and its result when there is one and the turn
    offers the tool (a prompt that holds a call must offer its tool); otherwise `entries` as they are."""
    if inbound.seen is None or not any(s.name == LOOK for s in offered):
        return entries
    camera, recording = inbound.seen
    arguments = {"camera": camera} if recording is None else {"camera": camera, "recording": recording}
    call = ToolCall(CALL_ID, LOOK, arguments)
    result = await CameraTools(inbound.household_id, conversation_id, said_id).call(call)
    return (*entries, ToolCalls((call,)), ToolResults((result,)))
