"""What a proposal asks the person to agree to, one record per kind and each kind's stored form: a `MoneyRule` to arm on
a reminder, a `ReminderSchedule` of a reminder whose turn acts, a `ReminderChange` to an existing one, a `WatchSchedule` of a watch whose turn acts, a
`HouseChange`, the `HeldCalls` of a turn that read outside words.
A kind belongs to one `Topic`, and a person has at most one pending proposal per conversation in each topic, so a
change to the house and a reminder she proposed in one conversation are agreed or refused apart. Stored as a JSON object
tagged by `kind`; code decodes it, never free text."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from ..criteria import condition
from ..criteria.condition import Condition
from ..home_assistant.change import Change
from . import deposit_rule
from . import repeat as repeats
from .deposit_rule import DepositRule
from .wakes import MAX_BRIEF, MAX_TOOLS, Reminder, stored_route


@dataclass(frozen=True)
class MoneyRule:
    """A money `rule` to arm on `reminder` (its `due_at` is when it was proposed; it has no repeat)."""

    reminder: Reminder
    rule: DepositRule


@dataclass(frozen=True)
class ReminderSchedule:
    """A reminder whose turn acts, to schedule as `reminder` is (its `due_at` the time it would fire)."""

    reminder: Reminder


@dataclass(frozen=True)
class ReminderChange:
    """The changes to make to the reminder with wake id `target`, as `reminder` gives them."""

    reminder: Reminder
    target: int


@dataclass(frozen=True)
class WatchSchedule:
    """A watch whose turn acts, to arm once the person agrees: `target` of `kind` for the reminder's person, ending at
    `until` or in `hours` (None: the kind's default), on bench `bench_id`'s talk. The `reminder` carries who and what:
    its brief is the watch's label, its tools the ones its turn uses, its `due_at` when it was proposed. `brief`
    and `standing` are the watch's own (`ashley.watches.model.Arm`): what the person agrees to includes them."""

    reminder: Reminder
    kind: str
    target: str
    until: Condition | None
    hours: float | None
    bench_id: int | None
    brief: str | None = None
    standing: bool = False


@dataclass(frozen=True)
class HouseChange:
    """A `change` to the house and the `summary` she gave the person (what it would do, in a line, from code, never the
    change's contents)."""

    change: Change
    summary: str


@dataclass(frozen=True)
class HeldCall:
    """A change a tainted turn would have made: the tool's `tool` name, its `arguments` as stored JSON, and the `summary`
    code wrote from the two, which is what the person is shown (`ashley.tools.outside_summary`). `explanation` is the
    action judge's one sentence on why it was held, empty when no judge was asked. `label` is the plain phrase the tool's
    spec gave it when it was held, empty when it had none; kept because a page move can stop the tool being offered."""

    tool: str
    arguments: Mapping[str, Any]
    summary: str
    explanation: str = ""
    label: str = ""


@dataclass(frozen=True)
class HeldCalls:
    """The `calls` a tainted turn held, in the order they were asked for."""

    calls: tuple[HeldCall, ...]


ReminderPayload = MoneyRule | ReminderSchedule | ReminderChange | WatchSchedule
Payload = ReminderPayload | HouseChange | HeldCalls


@dataclass(frozen=True)
class Topic[P: Payload]:
    """A family of payloads that replace one another: `name` as stored, and how a stored object becomes a `P`. `scope` is
    what a person's pending proposal of the topic is one per: each `conversation` (the default), or the `person`, whose
    proposals `Proposals.pending` and `take` find from any conversation."""

    name: str
    decode: Callable[[Mapping[str, Any]], P]
    scope: Literal["conversation", "person"] = "conversation"


def lapsed(payload: Payload, now: datetime) -> bool:
    """Whether the time `payload` was proposed for has come: only a reminder to schedule has one."""
    return isinstance(payload, ReminderSchedule) and payload.reminder.due_at <= now


def check(payload: Payload) -> None:
    """Raises ValueError for a reminder whose brief is outside 1 to `MAX_BRIEF` characters or holds a NUL, that names more
    than `MAX_TOOLS` tools,, or a money rule that repeats, and for held calls with no call."""
    if isinstance(payload, HeldCalls):
        if not payload.calls:
            raise ValueError("held calls hold at least one call")
        return
    if isinstance(payload, HouseChange):
        return
    r = payload.reminder
    if isinstance(payload, WatchSchedule) and payload.brief is not None and not (
            1 <= len(payload.brief) <= MAX_BRIEF and "\x00" not in payload.brief):
        raise ValueError(f"a proposed watch's brief is 1 to {MAX_BRIEF} characters, without a NUL")
    if not 1 <= len(r.brief) <= MAX_BRIEF or "\x00" in r.brief or (r.tools is not None and len(r.tools) > MAX_TOOLS):
        raise ValueError(f"a proposed reminder's brief is 1 to {MAX_BRIEF} characters, without a NUL")
    if isinstance(payload, MoneyRule) and r.repeat is not None:
        raise ValueError("a money rule has no repeat")


def encode(payload: Payload) -> tuple[str, dict[str, Any]]:
    """The topic name and stored object of `payload`."""
    match payload:
        case MoneyRule(reminder, rule):
            return REMINDERS.name, {"kind": "money_rule", "reminder": _reminder_to_json(reminder),
                                    "rule": deposit_rule.to_json(rule)}
        case ReminderSchedule(reminder):
            return REMINDERS.name, {"kind": "reminder", "reminder": _reminder_to_json(reminder)}
        case ReminderChange(reminder, target):
            return REMINDERS.name, {"kind": "reminder_change", "reminder": _reminder_to_json(reminder), "target": target}
        case WatchSchedule(reminder, kind, target, until, hours, bench_id, brief, standing):
            return REMINDERS.name, {"kind": "watch", "reminder": _reminder_to_json(reminder), "watch_kind": kind,
                                    "target": target, "until": None if until is None else condition.to_json(until),
                                    "hours": hours, "bench_id": bench_id, "brief": brief, "standing": standing}
        case HouseChange(change, summary):
            return HOUSE.name, {"kind": "house_change", "summary": summary, "change": {
                "op": change.op, "kind": change.kind, "id": change.id, "data": dict(change.data),
                "ids": list(change.ids)}}
        case HeldCalls(calls):
            return OUTSIDE.name, {"kind": "held_calls", "calls": [
                {"tool": c.tool, "arguments": dict(c.arguments), "summary": c.summary, "explanation": c.explanation,
                 "label": c.label}
                for c in calls]}


def _decode_reminders(raw: Mapping[str, Any]) -> ReminderPayload:
    reminder = _reminder_from_json(raw["reminder"])
    kind = raw["kind"]
    if kind == "watch":
        return WatchSchedule(reminder, str(raw["watch_kind"]), str(raw["target"]),
                             None if raw["until"] is None else condition.from_json(raw["until"]),
                             None if raw["hours"] is None else float(raw["hours"]),
                             None if raw["bench_id"] is None else int(raw["bench_id"]),
                             None if raw.get("brief") is None else str(raw["brief"]), bool(raw.get("standing", False)))
    if kind == "money_rule":
        return MoneyRule(reminder, deposit_rule.from_json(raw["rule"]))
    if kind == "reminder":
        return ReminderSchedule(reminder)
    if kind == "reminder_change":
        return ReminderChange(reminder, int(raw["target"]))
    raise ValueError(f"no reminder proposal of kind {kind}")


def _decode_house(raw: Mapping[str, Any]) -> HouseChange:
    if raw["kind"] != "house_change":
        raise ValueError(f"no house proposal of kind {raw['kind']}")
    c = raw["change"]
    return HouseChange(Change(c["op"], c["kind"], c["id"], c["data"], tuple(c["ids"])), str(raw["summary"]))


def _decode_outside(raw: Mapping[str, Any]) -> HeldCalls:
    if raw["kind"] != "held_calls":
        raise ValueError(f"no outside proposal of kind {raw['kind']}")
    return HeldCalls(tuple(HeldCall(str(c["tool"]), dict(c["arguments"]), str(c["summary"]), str(c.get("explanation", "")),
                                      str(c.get("label", ""))) for c in raw["calls"]))


def _reminder_to_json(r: Reminder) -> dict[str, Any]:
    return {"household_id": r.household_id, "person_id": r.person_id, "made_by": r.made_by, "brief": r.brief,
            "due_at": r.due_at.isoformat(), "repeat": None if r.repeat is None else repeats.to_json(r.repeat),
            "route": r.route, "tools": None if r.tools is None else list(r.tools), "taint": r.taint,
            "made_in": None if r.made_in is None else list(r.made_in), "device_id": r.device_id}


def _reminder_from_json(raw: Mapping[str, Any]) -> Reminder:
    return Reminder(int(raw["household_id"]), int(raw["person_id"]), int(raw["made_by"]), str(raw["brief"]),
                    datetime.fromisoformat(raw["due_at"]),
                    None if raw["repeat"] is None else repeats.from_json(raw["repeat"]), None,
                    stored_route(raw["route"]),
                    None if raw["tools"] is None else tuple(raw["tools"]),
                    None if raw.get("taint") is None else str(raw["taint"]),
                    None if raw.get("made_in") is None else (int(raw["made_in"][0]), int(raw["made_in"][1])),
                    None if raw.get("device_id") is None else int(raw["device_id"]))


REMINDERS = Topic[ReminderPayload]("reminder", _decode_reminders)
HOUSE = Topic[HouseChange]("house", _decode_house)
OUTSIDE = Topic[HeldCalls]("outside", _decode_outside, "person")
