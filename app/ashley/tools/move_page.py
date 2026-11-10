"""Moving the speaker's own page (`channels.turn_tools`), offered only on a thread whose channel is that page: one tool,
`move_page`, taking it to a room, or to one of the speaker's open benches. It publishes `ashley.live.events.PageMoved`
to the speaker's screens alone; each screen decides whether to follow now or offer to (the client's rule)."""

import json
import time

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..live.events import PageMoved, PageRoom, Shown
from ..live.live import Live
from ..workshop.model import Owner
from ..workshop.workshop import Workshop, WorkshopUnavailable
from . import bench_results
from .arrival import Arrival
from .tools import Catalogue, Tools

NAME = "move_page"
ROOMS: dict[str, PageRoom] = {"chat": "her", "workshop": "workshop", "bench": "workshop", "memory": "memory",
                              "devices": "devices", "connections": "connections"}
SPEC = ToolSpec(NAME, "Move the page the person is looking at to one of its rooms: chat (your room), workshop (their "
                "benches), bench (one of their open benches, by bench_id), memory (what you know of them), devices, or "
                "connections (the services and accounts they and the household connect). "
                "If they are in the middle of typing or editing, it waits for them to follow.",
                {"type": "object", "properties": {
                    "to": {"type": "string", "enum": list(ROOMS)},
                    "bench_id": {"type": "integer", "description": "the bench, when to is bench"}},
                 "required": ["to"]}, outside=False, tier="runs")
INSTRUCTIONS = ("The person is talking with you from their page, and you can move it with move_page when going "
                "somewhere helps what you are doing together: to a bench you just opened or are about to work on, "
                "back to chat when the work is done, to memory when they ask what you know. Say where you took them. Once you have "
                "taken them to a bench, the rest of this turn is a turn on that bench: you have its tools, and what you "
                "answer is said there, where they are now. When their message is about the work on one of these "
                "benches, take them there with move_page and do the work in this turn. Never tell them to go "
                "there themselves.")


class MovePageTools(Tools):
    def __init__(self, household_id: int, person_id: int, arrival: Arrival | None = None) -> None:
        self._owner = Owner(household_id, person_id)
        self._arrival = arrival

    async def catalogue(self) -> Catalogue:
        """`move_page`, its instructions, and in `now` the speaker's open benches (`_open`); None when the Workshop
        cannot be read."""
        return Catalogue((SPEC,), INSTRUCTIONS, now=await self._open())

    async def _open(self) -> str | None:
        """One line of JSON per open bench, the one changed most recently first: its id, title and kind of work (null
        until one is set). Nothing, None, when there is none open or the Workshop is unavailable."""
        try:
            benches = await services.get(Workshop).open_benches(self._owner)
        except WorkshopUnavailable:
            return None
        recent = sorted(benches, key=lambda b: (b.last_changed_at or b.opened_at, b.id), reverse=True)
        lines = [json.dumps({"bench_id": b.id, "title": b.title, "kind": b.work}, ensure_ascii=False) for b in recent]
        return "\n".join(["# Their open benches", "", *lines]) if lines else None

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: a destination that is not a room, or a bench that is not one of the speaker's open benches,
        is an error result and moves nothing. Each call logs one `tools.call` with the room and bench id."""
        started = time.monotonic()
        if call.name != NAME:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        to, bench_id = call.arguments.get("to"), call.arguments.get("bench_id")
        if not isinstance(to, str) or to not in ROOMS:
            return bench_results.failed(call, started, "bad_arguments", f"to is one of {', '.join(ROOMS)}")
        if to != "bench":
            return self._moved(call, started, ROOMS[to], None)
        if not isinstance(bench_id, int) or isinstance(bench_id, bool):
            return bench_results.failed(call, started, "bad_arguments", "a bench is named by its bench_id")
        try:
            benches = await services.get(Workshop).open_benches(self._owner)
        except WorkshopUnavailable:
            return bench_results.failed(call, started, "unavailable", "their benches cannot be read right now")
        if not any(b.id == bench_id for b in benches):
            return bench_results.failed(call, started, "no_such_bench", "that is not one of their open benches",
                                        bench=bench_id)
        return self._moved(call, started, "workshop", bench_id)

    def _moved(self, call: ToolCall, started: float, room: PageRoom, bench_id: int | None) -> ToolResult:
        shown = Shown(self._owner.household_id, self._owner.person_id)
        services.get(Live).publish(PageMoved(shown, room, bench_id))
        if self._arrival is not None:
            self._arrival.moved(bench_id)
        return bench_results.ok(call, started, {"moved_to": room, "bench_id": bench_id}, room=room, bench=bench_id)
