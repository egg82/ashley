"""`house_change` and `house_confirm`: changes to the house's configuration, offered where the speaker is known. She
writes automations, scripts and helpers, creates areas, floors and labels and changes entities' and devices' settings
on her own. A change `home_assistant/irreversible.json` names (a delete, removing an integration, restarting or
stopping the house, anything that destroys data) is not made: it is proposed (`senses.proposals`), she tells the
person what it would do, and `house_confirm` is offered only in a later person turn of the conversation, where it
carries out what was proposed and nothing else. Proposing and confirming need the reply to reach the speaker alone.

The `tools.call` line carries the tool, the outcome, the op, the kind and a wake-free proposal count; never an id, a name
or a config."""

import json
import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime

from .. import logs, services
from ..home_assistant.change import KINDS, OPS, Change, carry_out, check, op_of
from ..home_assistant.homes import Home, Homes, HomesUnavailable
from ..home_assistant.house import House, HouseRejected, HouseUnavailable, config_kind, record_kind
from ..home_assistant import irreversible
from ..home_assistant.irreversible import Irreversible
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..senses.proposal_gate import Refusal
from ..senses.proposal_payloads import HOUSE, HouseChange
from ..senses.proposals import Proposal, ProposalRefused, Proposals, ProposalsUnavailable, refusal
from . import house_args as args
from .house_look_config import load as load_look
from .house_query import Query
from .house_targets import entity_of, resolve
from .tools import Catalogue, Tools, ToolsUnavailable

log = logging.getLogger("ashley.tools")
_IRREVERSIBLE = irreversible.load()
_LOOK = load_look()
CHANGE = "house_change"
CONFIRM = "house_confirm"
_ARGUMENTS = ("op", "kind", "id", "data", "ids", "name", "area", "domain")
CHANGE_SPEC = ToolSpec(CHANGE, (
    "Change how the house is set up. op write: an automation or script (data the config object; id only to replace an existing one) or a helper (data "
    "{\"type\": \"input_boolean\", \"name\": ...}; with an id, it changes that helper); create: an area, floor or label "
    "(data name, aliases); update: an entity, device, area, floor or label's fields (id, data: name, aliases, area, ...); "
    "delete: an automation, script, helper, device, entity, area, floor, label or integration (id); perform: an action "
    "that needs the person's OK. You make configuration changes yourself. A delete, a removal, and an action that "
    "restarts or stops the house or destroys data are not done: they are proposed to the person, and you tell them in "
    "plain words what would happen and ask. house_find kind automation, script or helper gives the current config to "
    "change; a config you write replaces the one with that id."),
    {"type": "object", "properties": {
        "op": {"type": "string", "enum": list(OPS)}, "kind": {"type": "string", "enum": list(KINDS)},
        "id": {"type": "string", "description": "The config or record id; for perform, the action domain.name."},
        "data": {"type": "string", "description": "A JSON object in text: the config, the fields to set, or the action's data."},
        "ids": {"type": "array", "items": {"type": "string"}, "description": "perform: exact ids of the things."},
        "name": {"type": "string", "description": "perform: words from the thing's name."},
        "area": {"type": "string"}, "domain": {"type": "string"}},
     "required": ["op", "kind"]}, outside=False, tier="judged", label="Changed how the house is set up")
CONFIRM_SPEC = ToolSpec(CONFIRM, (
    "Carry out the change you proposed to the person earlier in this conversation, now that they have answered. Only "
    "call it when their latest message says yes to exactly what you proposed; it does what was proposed and nothing else."),
    {"type": "object", "properties": {}}, outside=False, agrees=True)
INSTRUCTIONS = (
    "You may change the house's setup yourself with house_change: write automations, scripts and helpers, create areas, "
    "and rename or move entities. Deleting anything, removing an integration, or restarting or stopping the house needs "
    "the person's OK: house_change proposes it, you say what would be deleted or stopped, and you ask; do not claim it is "
    "done. After they say yes, in their next message, house_confirm does it.")


class HouseChangeTools(Tools):
    def __init__(self, household_id: int, speaker_id: int, *, private: bool, turn: tuple[int, int] | None = None,
                 judge: Irreversible | None = None, ttl_s: float | None = None) -> None:
        """`turn` is the conversation and the person's turn she is answering; without it she can propose nothing.
        `judge` says what needs the person's OK and `ttl_s` how long a proposal can be confirmed; by default the shipped
        `irreversible.json` and `house_look.json`."""
        self._household_id, self._speaker_id, self._irreversible = household_id, speaker_id, judge or _IRREVERSIBLE
        self._ttl_s, self._private, self._turn = _LOOK.proposal_ttl_s if ttl_s is None else ttl_s, private, turn

    async def catalogue(self) -> Catalogue:
        if await self._house() is None:
            return Catalogue((), None)
        confirmable = await self._can_confirm()
        return Catalogue((CHANGE_SPEC, *((CONFIRM_SPEC,) if confirmable else ())), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, a bad argument, no house or the house refusing is an error result."""
        started = time.monotonic()
        if call.name not in (CHANGE, CONFIRM):
            return _done(call, "unknown_tool", started, ToolResult(call.id, f"no tool named {call.name}", True))
        try:
            house = await self._house()
            if house is None:
                return _done(call, "unavailable", started, ToolResult(call.id, "there is no house", True))
            if call.name == CHANGE:
                return await self._change(call, started, house)
            return await self._confirm(call, started, house)
        except ValueError as e:
            return _done(call, "bad_arguments", started, ToolResult(call.id, str(e), True))
        except HouseRejected as e:
            return _done(call, "error", started, ToolResult(call.id, f"the house refused it: {e.message}", True))
        except (HouseUnavailable, ProposalsUnavailable):
            return _done(call, "unavailable", started, ToolResult(call.id, "the house did not answer", True))

    async def _house(self) -> House | None:
        try:
            home: Home | None = await services.get(Homes).of(self._household_id)
        except HomesUnavailable as e:
            raise ToolsUnavailable("the household's house could not be read") from e
        return home.house if home is not None and home.house.offered() else None

    async def _can_confirm(self) -> bool:
        """Whether there is a proposal of the speaker's to carry out in this turn: she is offered `house_confirm` only
        then, so in the turn she proposes it she cannot confirm it."""
        if self._turn is None or not self._private:
            return False
        try:
            found = await services.get(Proposals).pending(self._speaker_id, self._turn[0], HOUSE)
        except ProposalsUnavailable:
            return False
        return found is not None and refusal(found, self._turn[1], datetime.now(UTC), self._ttl_s) is None

    async def _change(self, call: ToolCall, started: float, house: House) -> ToolResult:
        arguments = call.arguments
        args.only(arguments, CHANGE, _ARGUMENTS)
        op, kind = op_of(args.required(arguments, "op")), args.required(arguments, "kind")
        if op is None:
            raise ValueError(f"op is one of {', '.join(OPS)}")
        change = Change(op, kind, args.text(arguments, "id"), args.mapping(arguments, "data"), args.texts(arguments, "ids"))
        check(change)
        if change.op == "perform":
            change = await self._targeted(house, change, arguments)
        if not self._irreversible.covers(change.key()):
            if change.op == "perform":
                raise ValueError("that action does not need the person's OK: house_do runs it")
            done = await carry_out(house, change)
            return _done(call, "ok", started, ToolResult(call.id, _body(True, change, id=done)), op=op, kind=kind)
        return await self._propose(call, started, house, change)

    async def _targeted(self, house: House, change: Change, arguments: Mapping[str, object]) -> Change:
        query = Query(args.text(arguments, "area"), args.text(arguments, "domain"), args.text(arguments, "name"))
        found = resolve(tuple(entity_of(s) for s in await house.states()), query, change.ids)
        if found.ambiguous:
            raise ValueError(f"that fits several: {', '.join(found.ambiguous)}; say which")
        if found.unknown:
            raise ValueError("nothing in the house matches that")
        return Change(change.op, change.kind, change.id, change.data, found.ids)

    async def _propose(self, call: ToolCall, started: float, house: House, change: Change) -> ToolResult:
        if not self._private or self._turn is None:
            return _done(call, "needs_private", started, ToolResult(
                call.id, "that needs the person's OK and cannot be asked here: tell them to ask in a private conversation",
                True), op=change.op, kind=change.kind)
        summary = await _describe(house, change)
        await services.get(Proposals).propose(Proposal(
            self._household_id, self._speaker_id, *self._turn, datetime.now(UTC), HouseChange(change, summary)), self._ttl_s)
        body = _body(False, change, proposed=summary,
                     next="tell the person exactly this and ask; do it only after they answer yes in a later message")
        return _done(call, "proposed", started, ToolResult(call.id, body), op=change.op, kind=change.kind)

    async def _confirm(self, call: ToolCall, started: float, house: House) -> ToolResult:
        if self._turn is None or not self._private:
            return _done(call, "unknown_tool", started, ToolResult(call.id, f"no tool named {call.name}", True))
        try:
            proposal = await services.get(Proposals).take(self._speaker_id, self._turn[0], HOUSE, self._turn[1], self._ttl_s)
        except ProposalRefused as e:
            return _done(call, e.reason, started, ToolResult(call.id, _REFUSALS[e.reason], True))
        change = proposal.payload.change
        done = await carry_out(house, change)
        return _done(call, "ok", started, ToolResult(call.id, _body(True, change, id=done, did=proposal.payload.summary)),
                     op=change.op, kind=change.kind)


_REFUSALS: dict[Refusal, str] = {
    "none": "there is no proposal of yours to carry out in this conversation; propose it with house_change first",
    "expired": "that proposal has expired; propose it again and ask them",
    "same_turn": "the person has not answered since you proposed it; tell them what you would do and wait for their reply"}


def _body(done: bool, change: Change, **fields: str) -> str:
    return json.dumps({"done": done, "op": change.op, "kind": change.kind, **fields}, separators=(",", ":"))


async def _describe(house: House, change: Change) -> str:
    """One line for the person, from the change's op, kind and the name the house gives its id; never its contents."""
    what = await _named(house, change)
    if change.op == "perform":
        return f"run {change.id} on {len(change.ids)} thing(s)" if change.ids else f"run {change.id}"
    verb = "remove" if change.kind == "integration" else change.op
    return f"{verb} the {change.kind} {what}"


async def _named(house: House, change: Change) -> str:
    if change.id is None:
        return ""
    config, record = config_kind(change.kind), record_kind(change.kind)
    names: dict[str, str] = {}
    if config is not None:
        names = {i.id: i.name for i in await house.configs(config) if i.id is not None}
    elif record is not None:
        names = {r.id: r.name for r in await house.records(record)}
    return f"{names[change.id]} ({change.id})" if change.id in names else change.id


def _done(call: ToolCall, outcome: str, started: float, result: ToolResult, **fields: str) -> ToolResult:
    logs.info(log, "tools.call", **{**fields, "tool": call.name, "outcome": outcome,
                                    "duration_ms": int((time.monotonic() - started) * 1000)})
    return result
