"""Her watches as tools (`channels.turn_tools`): `watch` starts one on a target of a kind, `unwatch` stops it by what she
watched, and `watches` lists the speaker's own. Offered only where the reply reaches the speaker alone, and only while
the speaker has connected a source some kind reads (`Kind.available`). Arming reads the target once and needs no OK; a
watch that names a tool that acts is only proposed (`WatchSchedule`, in the reminders' topic) and `arm_reminder` agrees
it from a later person turn, exactly as for a reminder (`usable` is the tools the speaker has in this turn, not these).
Logs `tools.call` with the tool, outcome and watch id, never a target, label or value."""

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .. import services
from ..connections.connections import ConnectionsUnavailable
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..senses.deposit_config import CONFIG as DEPOSITS
from ..senses.proposal_payloads import WatchSchedule
from ..senses.wakes import Reminder
from ..senses.proposals import Proposal, Proposals, ProposalsUnavailable
from ..watches import arming
from ..watches.arming import Ask
from ..watches.config import CONFIG
from ..watches.model import Watch
from ..watches.registry import KINDS
from ..watches.watches import Watches, WatchesUnavailable
from . import bench_results, reminder_shape as shape, tainted, watch_agreed, watch_conditions, watch_sort, watch_specs as specs
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools, ToolsUnavailable


class WatchTools(Tools):
    def __init__(self, household_id: int, speaker_id: int, *, bench_id: int | None = None,
                 turn: tuple[int, int] | None = None, usable: Callable[[], Tools] | None = None) -> None:
        """`turn` is the conversation and the person's turn she is answering; without it she can propose nothing.
        `usable` gives the tools the speaker has in this turn (not these ones): a watch may name those."""
        self._household_id, self._speaker_id, self._bench_id, self._turn = household_id, speaker_id, bench_id, turn
        self._usable = usable

    async def catalogue(self) -> Catalogue:
        """Empty when the speaker has connected nothing a kind reads. Raises ToolsUnavailable when connections cannot
        be read."""
        kinds = await self._kinds()
        if not kinds:
            return Catalogue((), None)
        acting = bool(await self._usable_specs())
        tracked = {f for k in kinds for f in CONFIG.kinds[k].track}
        top = max(CONFIG.kinds[k].max_hours for k in kinds)
        return Catalogue((specs.watch(kinds, tracked, top, acting), specs.unwatch(kinds), specs.WATCHES_SPEC),
                         specs.INSTRUCTIONS + (specs.ACTING if acting else ""))

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, a bad argument, a kind the speaker cannot use, a target that is not there or
        the store out of reach is an error result."""
        started = time.monotonic()
        if call.name not in (specs.WATCH, specs.UNWATCH, specs.WATCHES):
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            kinds = await self._kinds()
            if call.name == specs.WATCHES:
                return await self._list(call, started)
            if call.name == specs.UNWATCH:
                return await self._unwatch(call, started, kinds)
            return await self._watch(call, started, kinds)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        except (ToolsUnavailable, WatchesUnavailable):
            return bench_results.failed(call, started, "unavailable", "watches cannot be reached right now")

    async def _kinds(self) -> tuple[str, ...]:
        """The kinds whose source the speaker has connected. Raises ToolsUnavailable."""
        try:
            return tuple([k for k in CONFIG.kinds
                          if await KINDS.get(k).available(self._household_id, self._speaker_id)])
        except ConnectionsUnavailable as e:
            raise ToolsUnavailable("connections unavailable") from e

    async def _usable_specs(self) -> Mapping[str, ToolSpec]:
        """The tools a watch may name, by name: the speaker's own, when a turn exists to propose in."""
        if self._usable is None or self._turn is None:
            return {}
        try:
            return {s.name: s for s in (await self._usable().catalogue()).specs}
        except ToolsUnavailable:
            return {}

    async def _watch(self, call: ToolCall, started: float, kinds: tuple[str, ...]) -> ToolResult:
        args = call.arguments
        check_names(args, specs.watch(kinds, (), 1, True))
        kind, target = _kind(args.get("kind"), kinds), _target(args.get("target"))
        until = watch_conditions.parse(args.get("until"), CONFIG.kinds[kind].track)
        hours = _hours(kind, args.get("hours"))
        usable = await self._usable_specs()
        tools = shape.tools_of(args.get("tools"), usable)
        ask = Ask(self._household_id, self._speaker_id, self._bench_id, kind, target, until, tools, hours,
                  watch_sort.brief(args), watch_sort.standing(args), tainted.current(), tainted.made_in())
        if shape.acts(tools, usable):
            return await self._proposed(call, started, ask, tools or ())
        return await watch_agreed.arm(call, started, ask)

    async def _proposed(self, call: ToolCall, started: float, ask: Ask, tools: tuple[str, ...]) -> ToolResult:
        """Read the target, then store the watch as a proposal: a watch that acts is armed only after the person agreed."""
        if self._turn is None:
            raise ToolsUnavailable("no turn to propose in")
        now = datetime.now(UTC)
        seen = await watch_agreed.read(call, started, ask, now)
        if isinstance(seen, ToolResult):
            return seen
        reminder = Reminder(ask.household_id, ask.person_id, self._speaker_id, seen.label, now, None, tools=tools,
                            taint=ask.taint, made_in=ask.made_in)
        schedule = WatchSchedule(reminder, ask.kind, ask.target, ask.until, ask.hours, ask.bench_id, ask.brief,
                                 ask.standing)
        try:
            await services.get(Proposals).propose(
                Proposal(ask.household_id, self._speaker_id, *self._turn, now, schedule), DEPOSITS.proposal_ttl_s)
        except ValueError as e:
            raise BadArguments(str(e)) from e
        except ProposalsUnavailable as e:
            raise ToolsUnavailable("proposals unavailable") from e
        return bench_results.ok(call, started, {
            "armed": False, "label": seen.label, "tools": list(tools), "standing": ask.standing,
            "next": "tell the person in plain words what you will watch and what you will do when it changes, with "
                    "which tools; set it with arm_reminder only after they answer yes in a later message"},
            outside=KINDS.get(ask.kind).outside)

    async def _unwatch(self, call: ToolCall, started: float, kinds: tuple[str, ...]) -> ToolResult:
        check_names(call.arguments, specs.unwatch(kinds))
        kind, target = _kind(call.arguments.get("kind"), kinds), _target(call.arguments.get("target"))
        if not await services.get(Watches).disarm(self._household_id, self._speaker_id, kind, target):
            return bench_results.failed(call, started, "not_found", "you are not watching that; watches lists them")
        return bench_results.ok(call, started, {"stopped": True})

    async def _list(self, call: ToolCall, started: float) -> ToolResult:
        check_names(call.arguments, specs.WATCHES_SPEC)
        zone = await watch_agreed.zone_of(self._household_id)
        found = await services.get(Watches).live(self._household_id, self._speaker_id)
        return bench_results.ok(call, started, {"watches": [_shown(w, zone) for w in found]}, count=len(found))


def _kind(raw: object, kinds: tuple[str, ...]) -> str:
    for k in kinds:
        if raw == k:
            return k
    raise BadArguments("kind is one of " + ", ".join(kinds))


def _target(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > specs.MAX_TARGET or "\x00" in raw:
        raise BadArguments(f"target is 1 to {specs.MAX_TARGET} characters")
    return raw.strip()


def _hours(kind: str, raw: object) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise BadArguments("hours is a number")
    try:
        return arming.hours_of(kind, float(raw))
    except ValueError as e:
        raise BadArguments(str(e)) from e


def _shown(w: Watch, zone: ZoneInfo) -> dict[str, object]:
    shown: dict[str, object] = {
        "kind": w.kind, "target": w.target, "label": w.label,
        "until": None if w.until is None else watch_conditions.say(w.until),
        "expires": watch_agreed.local(w.expires_at, zone)}
    if w.standing:
        shown["standing"] = True
    if w.brief is not None:
        shown["brief"] = w.brief
    if w.state == "paused":
        shown["paused"] = w.reason
    return shown
