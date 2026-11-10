"""Opening a bench for the speaker from their own web chat (`channels.turn_tools`): one tool, `open_bench`, whose title
is hers to choose. It returns the bench's id and the room's path, `/workshop/<id>`, for her reply to link to."""

import time

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..workshop.model import Owner
from ..workshop.workshop import UnknownOwner, Workshop, WorkshopUnavailable
from . import bench_results
from .arrival import Arrival
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools

NAME = "open_bench"
SPEC = ToolSpec(NAME, "Open a new bench for the person you are talking with: a board where you and they make something "
                "together out of notes and documents. Returns its id and the path to link to.",
                {"type": "object", "properties": {"title": {"type": "string", "description": "a short name for it"}},
                 "required": ["title"]}, outside=False, tier="runs")
INSTRUCTIONS = ("An ask that will take several rounds, or that is a plan, a list to build up, a draft, a design, or "
                "work from sources you will gather, belongs on a bench. Open one with open_bench yourself in the same "
                "turn, without asking first, and say in your reply that you have. Link it in your reply as "
                "[its title](path), with the path open_bench gives.")


def path_of(bench_id: int) -> str:
    """The room's route for a bench, as the web client serves it."""
    return f"/workshop/{bench_id}"


class OpenBenchTools(Tools):
    def __init__(self, household_id: int, person_id: int, arrival: Arrival | None = None) -> None:
        self._owner = Owner(household_id, person_id)
        self._arrival = arrival

    async def catalogue(self) -> Catalogue:
        return Catalogue((SPEC,), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an argument it does not define, a bad title, an owner the Workshop does not know or a Workshop out of reach is an error
        result, logged `tools.call`."""
        started = time.monotonic()
        if call.name != NAME:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        title = call.arguments.get("title")
        try:
            check_names(call.arguments, SPEC)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        if not isinstance(title, str):
            return bench_results.failed(call, started, "bad_arguments", "title is a string")
        try:
            bench = await services.get(Workshop).open(self._owner, title)
        except ValueError:
            return bench_results.failed(call, started, "bad_title", "a title is short, not empty and holds no NUL")
        except (UnknownOwner, WorkshopUnavailable):
            return bench_results.failed(call, started, "unavailable", "a bench cannot be opened right now")
        if self._arrival is not None:
            self._arrival.opened(bench.id)
        return bench_results.ok(call, started, {"bench_id": bench.id, "path": path_of(bench.id)}, bench=bench.id)
