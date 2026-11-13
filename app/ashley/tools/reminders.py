"""Her reminders as tools (`channels.turn_tools`): `remind` sets one for a person of the household, wherever the channel
names the speaker; `reminders` lists, `change_reminder` changes and `cancel_reminder` cancels the speaker's own (for them
or set by them), only where the reply reaches the speaker alone (`private`), since what a reminder says may carry money.
Each is a wake she sets for herself (`ashley.senses.wakes.Wakes.schedule`, `edit`), fired by the `wakes` singleton;
`remind_on_money`, offered where the household has connected Sure, sets one that waits on money coming in or going out
(`ashley.senses.deposits`). A reminder may name the tools its turn uses (`usable`, the tools the speaker has in this
turn): one that acts is only proposed, as a money rule is, and `arm_reminder` agrees it from a later person turn. Times
are wall-clock times in the household's zone. Logs `tools.call` with the tool, outcome and wake id, never an argument."""

import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import services
from ..connections.connections import Connections, ConnectionsUnavailable
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..people.model import Household
from ..people.people import People, PeopleUnavailable
from ..senses.deposit_rule import describe
from ..senses.deposit_config import CONFIG
from ..senses.deposits import Deposits, DepositsUnavailable
from ..senses.proposal_gate import Refusal
from ..senses.proposal_payloads import REMINDERS, MoneyRule, ReminderChange, ReminderPayload, ReminderSchedule, WatchSchedule
from ..senses.proposals import Proposal, ProposalRefused, Proposals, ProposalsUnavailable, refusal
from ..senses.repeat import LOCAL_FORMAT
from ..senses.wakes import Reminder, Route, Scheduled, Wakes, WakesUnavailable
from . import bench_results, money_rule_args, reminder_shape as shape, reminder_specs as specs, tainted, watch_agreed
from .bench_args import BadArguments, check_names
from .errand_step import CONFIG as ERRAND
from .tools import Catalogue, Tools, ToolsUnavailable


_REFUSALS: dict[Refusal, str] = {
    "none": "there is no proposal of yours to arm in this conversation; propose it with remind_on_money first",
    "expired": "that proposal has expired; propose it again and ask them",
    "same_turn": "the person has not answered since you proposed it; tell them the rule and wait for their reply"}


class ReminderTools(Tools):
    def __init__(self, household_id: int, speaker_id: int, *, private: bool, turn: tuple[int, int] | None = None,
                 usable: Callable[[], Tools] | None = None,
                 routable: Callable[[Route, int], Awaitable[bool]] | None = None) -> None:
        """`turn` is the conversation and the person's turn she is answering; without it she can propose nothing.
        `usable` gives the tools the speaker has in this turn (not these ones): a reminder may name those, and with
        none it names none. `routable` says whether a device of the household may carry a `room` or `screen` route
        (raising ToolsUnavailable when that cannot be told); without it neither can be set."""
        self._household_id, self._speaker_id, self._private, self._turn = household_id, speaker_id, private, turn
        self._usable, self._routable = usable, routable

    async def catalogue(self) -> Catalogue:
        household = await self._household()
        names = sorted({p.name for p in household.people})
        acting = bool(await self._usable_specs())
        remind = specs.remind(names, acting)
        if not self._private:
            return Catalogue((remind,), specs.INSTRUCTIONS)
        deposits = await self._sees_deposits()
        can_arm = await self._can_arm()
        return Catalogue((remind, *((specs.remind_on_money(names),) if deposits else ()),
                          *((specs.ARM_SPEC,) if can_arm else ()), specs.LIST_SPEC, specs.CANCEL_SPEC,
                          specs.change_reminder(acting)),
                         specs.INSTRUCTIONS + (specs.ACTING if acting else "") + specs.PRIVATE
                         + (specs.ON_MONEY_INSTRUCTIONS if deposits else "") + (specs.ARM_INSTRUCTIONS if can_arm else ""))

    async def _usable_specs(self) -> Mapping[str, ToolSpec]:
        """The tools a reminder may name, by name: the speaker's own in a private turn that can propose, else none."""
        if self._usable is None or not self._private or self._turn is None:
            return {}
        try:
            return {s.name: s for s in (await self._usable().catalogue()).specs}
        except ToolsUnavailable:
            return {}

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, a bad argument, a time passed, or the store or People out of reach is an
        error result."""
        started = time.monotonic()
        allowed = ((specs.REMIND, specs.LIST, specs.CANCEL, specs.CHANGE, specs.ON_MONEY, specs.ARM)
                   if self._private else (specs.REMIND,))
        if call.name not in allowed:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            household = await self._household()
            if call.name == specs.REMIND:
                return await self._remind(call, started, household)
            if call.name == specs.ON_MONEY:
                return await self._on_money(call, started, household)
            if call.name == specs.ARM:
                return await self._arm(call, started)
            if call.name == specs.LIST:
                return await self._list(call, started, household)
            if call.name == specs.CHANGE:
                return await self._change(call, started, household)
            return await self._cancel(call, started)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        except (ToolsUnavailable, WakesUnavailable):
            return bench_results.failed(call, started, "unavailable", "reminders cannot be reached right now")

    async def _can_arm(self) -> bool:
        """Whether there is a proposal of the speaker's to arm in this turn: she is offered `arm_money_reminder` only
        then, so in the turn she proposes it she cannot arm it, nor say she did by a refusal she then ignores."""
        if self._turn is None:
            return False
        try:
            found = await services.get(Proposals).pending(self._speaker_id, self._turn[0], REMINDERS)
        except ProposalsUnavailable:
            return False
        return found is not None and refusal(found, self._turn[1], datetime.now(UTC), CONFIG.proposal_ttl_s) is None

    async def _household(self) -> Household:
        try:
            household = await services.get(People).household(self._household_id)
        except PeopleUnavailable as e:
            raise ToolsUnavailable("people unavailable") from e
        if household is None:
            raise ToolsUnavailable("no such household")
        return household

    async def _remind(self, call: ToolCall, started: float, household: Household) -> ToolResult:
        args = call.arguments
        check_names(args, specs.remind(()))
        zone = ZoneInfo(household.timezone)
        local = _local_at(args.get("at"))
        repeat = shape.repeat_of(args, local, None)
        due_at = shape.first_due(repeat, local, zone, datetime.now(UTC))
        usable = await self._usable_specs()
        tools = shape.tools_of(args.get("tools"), usable)
        route, device = await self._route(args, "phone", None)
        reminder = Reminder(self._household_id, _person(household, args.get("for")), self._speaker_id,
                            _what(args.get("what")), due_at, repeat, None, route, tools, tainted.current(),
                            tainted.made_in(), device, _ends(args.get("errand_hours"), due_at, repeat))
        if shape.acts(tools, usable):
            return await self._proposed(call, started, reminder, None, zone)
        try:
            made = await services.get(Wakes).schedule(reminder)
        except ValueError as e:
            raise BadArguments("what is 1 to 500 characters") from e
        return bench_results.ok(call, started, {"id": made, "at": due_at.astimezone(zone).strftime(LOCAL_FORMAT)},
                                wake=made)

    async def _proposed(self, call: ToolCall, started: float, reminder: Reminder, target: int | None,
                        zone: ZoneInfo) -> ToolResult:
        """Store `reminder` (or, with `target`, the changed reminder it would replace) as a proposal: a reminder that acts
        is set only after the person has agreed, as a money rule is."""
        if self._turn is None:
            raise ToolsUnavailable("no turn to propose in")
        if reminder.person_id != self._speaker_id:
            raise BadArguments("a reminder that acts is for themselves, not another person")
        try:
            payload = ReminderSchedule(reminder) if target is None else ReminderChange(reminder, target)
            await services.get(Proposals).propose(
                Proposal(reminder.household_id, reminder.made_by, *self._turn, datetime.now(UTC), payload),
                CONFIG.proposal_ttl_s)
        except ValueError as e:
            raise BadArguments("what is 1 to 500 characters") from e
        except ProposalsUnavailable as e:
            raise ToolsUnavailable("proposals unavailable") from e
        return bench_results.ok(call, started, {
            "armed": False, "at": reminder.due_at.astimezone(zone).strftime(LOCAL_FORMAT),
            "tools": list(reminder.tools or ()),
            "next": "tell the person in plain words what it will do, when and with which tools; set it with "
                    "arm_reminder only after they answer yes in a later message"}, wake=target)

    async def _change(self, call: ToolCall, started: float, household: Household) -> ToolResult:
        args = call.arguments
        check_names(args, specs.change_reminder())
        wake_id = args.get("id")
        if not isinstance(wake_id, int) or isinstance(wake_id, bool):
            raise BadArguments("id is an integer")
        found = [s for s in await services.get(Wakes).reminders(self._household_id, self._speaker_id)
                 if s.id == wake_id and s.state == "scheduled"]
        if not found:
            return bench_results.failed(call, started, "not_found", "no reminder of theirs still to fire has that id; list them again")
        zone, current = ZoneInfo(household.timezone), found[0]
        usable = await self._usable_specs()
        changed = _changed(args, current, zone, usable,
                           await self._route(args, current.reminder.route, current.reminder.device_id))
        before = set(current.reminder.tools or ())
        if shape.acts(tuple(n for n in changed.tools or () if n not in before), usable):
            return await self._proposed(call, started, changed, wake_id, zone)
        if not await services.get(Wakes).edit(self._household_id, self._speaker_id, wake_id, changed):
            return bench_results.failed(call, started, "not_found", "that reminder has fired or is gone; list them again")
        return bench_results.ok(call, started, {"changed": wake_id,
                                                "at": changed.due_at.astimezone(zone).strftime(LOCAL_FORMAT)}, wake=wake_id)

    async def _route(self, args: Mapping[str, object], route: Route, device: int | None) -> tuple[Route, int | None]:
        """The route and device the arguments give, `route` and `device` where they leave them out; the device is one
        `routable` takes for that route."""
        route = shape.route_of(args.get("delivery"), route)
        if route not in ("room", "screen"):
            if args.get("device") is not None:
                raise BadArguments("device is only for room or screen")
            return route, None
        raw = args.get("device", device)
        if isinstance(raw, int) and not isinstance(raw, bool) and self._routable is not None \
                and await self._routable(route, raw):
            return route, raw
        raise BadArguments(f"device is the id of a {'satellite' if route == 'room' else 'screen'} from "
                           "household_devices")

    async def _sees_deposits(self) -> bool:
        """Whether her money tools can show her past deposits: the household has connected Sure."""
        try:
            return any(c.kind == "sure" for c in await services.get(Connections).of_household(self._household_id))
        except ConnectionsUnavailable:
            return False

    async def _on_money(self, call: ToolCall, started: float, household: Household) -> ToolResult:
        args = call.arguments
        check_names(args, specs.remind_on_money(()))
        if not await self._sees_deposits():
            return bench_results.failed(call, started, "not_connected", "the household has not connected Sure")
        try:
            rule = money_rule_args.rule_of(args)
            reminder = Reminder(self._household_id, _person(household, args.get("for")), self._speaker_id,
                                _what(args.get("what")), datetime.now(UTC), None, taint=tainted.current(),
                                made_in=tainted.made_in())
            if self._turn is None:
                raise ToolsUnavailable("no turn to propose in")
            await services.get(Proposals).propose(
                Proposal(reminder.household_id, reminder.made_by, *self._turn, reminder.due_at, MoneyRule(reminder, rule)),
                CONFIG.proposal_ttl_s)
        except ValueError as e:
            raise BadArguments(str(e)) from e
        except ProposalsUnavailable as e:
            raise ToolsUnavailable("proposals unavailable") from e
        return bench_results.ok(call, started, {"when": describe(rule), "armed": False,
                                                "next": "tell the person this rule in plain words; arm it after they answer in a later message"})

    async def _arm(self, call: ToolCall, started: float) -> ToolResult:
        check_names(call.arguments, specs.ARM_SPEC)
        if self._turn is None:
            raise ToolsUnavailable("no turn to arm in")
        try:
            proposal = await services.get(Proposals).take(self._speaker_id, self._turn[0], REMINDERS, self._turn[1],
                                                          CONFIG.proposal_ttl_s)
            return await self._agreed(call, started, proposal)
        except ProposalRefused as e:
            return bench_results.failed(call, started, e.reason, _REFUSALS[e.reason])
        except (ProposalsUnavailable, DepositsUnavailable) as e:
            raise ToolsUnavailable("deposits unavailable") from e

    async def _agreed(self, call: ToolCall, started: float, proposal: Proposal[ReminderPayload]) -> ToolResult:
        """What agreeing to `proposal` does: arms its money rule, makes the change it proposed, or schedules it."""
        payload = proposal.payload
        if isinstance(payload, WatchSchedule):
            return await watch_agreed.arm_agreed(call, started, payload)
        r = payload.reminder
        if isinstance(payload, MoneyRule):
            rule = payload.rule
            made = await services.get(Deposits).arm(Reminder(r.household_id, r.person_id, r.made_by, r.brief,
                                                             datetime.now(UTC), None, route=r.route, tools=r.tools,
                                                             taint=r.taint, made_in=r.made_in, device_id=r.device_id),
                                                    rule)
            return bench_results.ok(call, started, {"id": made, "when": describe(rule)}, wake=made)
        if isinstance(payload, ReminderChange):
            if not await services.get(Wakes).edit(self._household_id, self._speaker_id, payload.target, r):
                return bench_results.failed(call, started, "not_found", "that reminder has fired or is gone")
            return bench_results.ok(call, started, {"changed": payload.target}, wake=payload.target)
        made = await services.get(Wakes).schedule(r)
        return bench_results.ok(call, started, {"id": made}, wake=made)

    async def _list(self, call: ToolCall, started: float, household: Household) -> ToolResult:
        check_names(call.arguments, specs.LIST_SPEC)
        found = await services.get(Wakes).reminders(self._household_id, self._speaker_id)
        names = {p.id: p.name for p in household.people}
        zone = ZoneInfo(household.timezone)
        return bench_results.ok(call, started, {"reminders": [_shown(s, names, zone) for s in found]},
                                count=len(found))

    async def _cancel(self, call: ToolCall, started: float) -> ToolResult:
        check_names(call.arguments, specs.CANCEL_SPEC)
        wake_id = call.arguments.get("id")
        if not isinstance(wake_id, int) or isinstance(wake_id, bool):
            raise BadArguments("id is an integer")
        if not await services.get(Wakes).cancel(self._household_id, self._speaker_id, wake_id):
            return bench_results.failed(call, started, "not_found", "no reminder of theirs has that id; list them again")
        return bench_results.ok(call, started, {"cancelled": wake_id}, wake=wake_id)


def _local_at(raw: object) -> datetime:
    """`raw` as a wall-clock time; a date alone is `DEFAULT_TIME` that day."""
    text = f"{raw}T{specs.DEFAULT_TIME}" if isinstance(raw, str) and len(raw) == len("YYYY-MM-DD") else raw
    try:
        local = datetime.strptime(text, LOCAL_FORMAT) if isinstance(text, str) else None
    except ValueError:
        local = None
    if local is None or local.strftime(LOCAL_FORMAT) != text:
        raise BadArguments("at is the local time as YYYY-MM-DDTHH:MM, or a date as YYYY-MM-DD")
    return local


def _ends(raw: object, due_at: datetime, repeat: object) -> datetime | None:
    """When an errand of `raw` hours from `due_at` ends; None for a reminder (`raw` left out)."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not 0 < raw <= ERRAND.max_hours:
        raise BadArguments(f"errand_hours is a number of hours above 0 and at most {ERRAND.max_hours:g}")
    if repeat is not None:
        raise BadArguments("an errand never repeats; leave out repeat or errand_hours")
    return due_at + timedelta(hours=raw)


def _person(household: Household, raw: object) -> int:
    found = [p.id for p in household.people if p.name == raw]
    if len(found) != 1:
        raise BadArguments("for is one of the household's names")
    return found[0]


def _what(raw: object) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BadArguments("what is what to remind them of")
    return raw


def _changed(args: Mapping[str, object], current: Scheduled, zone: ZoneInfo, usable: Mapping[str, ToolSpec],
             routed: tuple[Route, int | None]) -> Reminder:
    """`current`'s reminder with the arguments applied and its route and device `routed`; what is not given stays."""
    r = current.reminder
    timing = "at" in args or any(k in args for k in shape.REPEAT_KEYS)
    if timing and current.deposit is not None:
        raise BadArguments("a reminder that waits on money has no time to change")
    due_at, repeat = r.due_at, r.repeat
    if timing:
        local = _local_at(args["at"]) if "at" in args else r.due_at.astimezone(zone).replace(tzinfo=None)
        repeat = shape.repeat_of(args, local, r.repeat)
        due_at = shape.first_due(repeat, local, zone, datetime.now(UTC))
    if r.ends_at is not None and (repeat is not None or due_at > r.ends_at):
        raise BadArguments("an errand never repeats, and its next check falls before it ends")
    tools = shape.tools_of(args["tools"], usable) if "tools" in args else r.tools
    return Reminder(r.household_id, r.person_id, r.made_by, _what(args["what"]) if "what" in args else r.brief,
                    due_at, repeat, None, routed[0], tools, tainted.current() or r.taint,
                    tainted.made_in() if tainted.current() else r.made_in, routed[1], r.ends_at, r.plan)


def _shown(s: Scheduled, names: Mapping[int, str], zone: ZoneInfo) -> dict[str, object]:
    r = s.reminder
    shown: dict[str, object] = {
        "id": s.id, "for": names.get(r.person_id), "made_by": names.get(r.made_by),
        "at": r.due_at.astimezone(zone).strftime(LOCAL_FORMAT),
        "repeat": shape.ONCE if r.repeat is None else r.repeat.freq,
        "every": None if r.repeat is None else r.repeat.every, "what": r.brief, "state": s.state}
    if r.repeat is not None and r.repeat.weekdays:
        shown["weekdays"] = [shape.DAYS[d] for d in r.repeat.weekdays]
    if r.repeat is not None and r.repeat.nth is not None:
        shown["nth"] = r.repeat.nth
    if r.repeat is not None and r.repeat.until is not None:
        shown["until"] = r.repeat.until.isoformat()
    if r.route != "phone":
        shown["delivery"] = r.route
    if r.device_id is not None:
        shown["device"] = r.device_id
    if r.tools is not None:
        shown["tools"] = list(r.tools)
    if r.ends_at is not None:
        shown["errand_until"] = r.ends_at.astimezone(zone).strftime(LOCAL_FORMAT)
    return shown
