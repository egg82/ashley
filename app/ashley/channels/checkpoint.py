"""A turn's checkpoint (`ashley.channels.inflight`) and its JSON, the text `InFlight` keeps. It holds what a runner
on another pod needs to finish the turn as it began: the message, the system prompt as built, how far the loop got,
and what the end of the turn needs (the speaker, the fact ids she was offered, the phone a reply may go to)."""

import base64
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any, get_args

from ..inference.model import Entry, Image, Message, SystemPrompt, ToolCall, ToolCalls, ToolResult, ToolResults
from ..initiative.moment import Moment
from ..tools.action_judge import JudgeUnavailable, Verdict, checked
from .escalation import Trigger
from .keep import Act
from .model import Inbound, Taint
from .tool_loop import Progress

INTERRUPTED = ("This call was interrupted and may or may not have taken effect. Check before doing it again, and "
               "say so if you cannot tell.")


@dataclass(frozen=True)
class Acting:
    """The memory act left once her turn `hers` is stored; `started` once it began, after which it is never begun
    again."""

    act: Act
    hers: int
    started: bool = False


@dataclass(frozen=True)
class Checkpoint:
    """`started`: the ids of changes in the round in flight that began and have no result. `turn`: the token naming
    the turn on the screens (`live_turn.Showing`), so a runner that finishes it ends the state its first runner
    showed. `acting`: set once her turn is stored and a memory act is all that is left. `left`: the person turn was left
    to a turn of its own by a steering turn that ended without it (`InFlight.drop_leaving`), and nothing is built yet:
    the runner that claims it answers it from the start (`channels.left`). `carried`: once the turn's page landed on a
    bench and its ask was carried into that bench's talk (`continued.carried`), the talk and the carried ask: the turn
    is that talk's running turn, handed its messages. `escalated`: what escalated the turn to the stronger route
    (`channels.escalation`), set before its holding line goes out; a runner that resumes it starts there.
    `unreachable_told`: the line that she could not reach her thinking is already said, so no runner says it twice.
    `tainted`: what tainted the turn (`channels.taint`): its origin (`Inbound.taint`) from the start, else the name of
    the first tool whose result carried outside words; None while it has read none. It never clears. `changed`: a change
    began on the turn (`Steps.starting`); it never clears. `judged`: the action judge's verdict on each call it judged,
    by call id (`Steps.judged`); it never clears. `worked_s`: the seconds of work in the turn's current window, which a
    runner that resumes it counts its deadline from (`Steps.worked`), never the time spent waiting to be resumed.
    `windows`: how many fresh windows the turn has taken (`Steps.windowed`); it never clears. `cut_off`: how many steps
    were asked again to act small after a reply was cut off at the token limit (`Steps.cut`); it never clears."""

    inbound: Inbound
    conversation_id: int
    said_id: int
    speaker_id: int | None
    system: Mapping[str, SystemPrompt]
    progress: Progress
    started: frozenset[str] = frozenset()
    offered: frozenset[int] = frozenset()
    phone: int | None = None
    turn: str | None = None
    acting: Acting | None = None
    left: bool = False
    carried: tuple[int, int] | None = None
    escalated: Trigger | None = None
    unreachable_told: bool = False
    tainted: str | None = None
    changed: bool = False
    judged: Mapping[str, Verdict] = field(default_factory=dict[str, Verdict])
    worked_s: float = 0.0
    windows: int = 0
    cut_off: int = 0

    def to_resume(self) -> Progress:
        """The progress a new runner goes on from: each change that began with no result is done, as an error saying
        it may or may not have taken effect, so it is never run again."""
        lost = {i: ToolResult(i, INTERRUPTED, is_error=True) for i in self.started if i not in self.progress.done}
        return replace(self.progress, done={**self.progress.done, **lost}) if lost else self.progress


def dumps(checkpoint: Checkpoint) -> str:
    progress = checkpoint.progress
    return json.dumps({
        "inbound": asdict(replace(checkpoint.inbound, attachment=None)),
        "conversation_id": checkpoint.conversation_id,
        "said_id": checkpoint.said_id,
        "speaker_id": checkpoint.speaker_id,
        "system": {k: {"stable": v.stable, "moment": v.moment} for k, v in checkpoint.system.items()},
        "entries": [_entry(e) for e in progress.entries],
        "rounds": progress.rounds,
        "calls": progress.calls,
        "asked": None if progress.asked is None else _entry(progress.asked),
        "done": [_result(r) for r in progress.done.values()],
        "steered": list(progress.steered),
        "started": sorted(checkpoint.started),
        "offered": sorted(checkpoint.offered),
        "phone": checkpoint.phone,
        "turn": checkpoint.turn,
        "acting": None if checkpoint.acting is None else _acting(checkpoint.acting),
        "left": checkpoint.left,
        "carried": None if checkpoint.carried is None else list(checkpoint.carried),
        "escalated": checkpoint.escalated,
        "unreachable_told": checkpoint.unreachable_told,
        "tainted": checkpoint.tainted,
        "changed": checkpoint.changed,
        "judged": {i: [v.decision, v.reason, v.explanation] for i, v in checkpoint.judged.items()},
        "worked_s": checkpoint.worked_s,
        "windows": checkpoint.windows,
        "cut_off": checkpoint.cut_off,
    })


def loads(text: str) -> Checkpoint:
    """Raises ValueError (json.JSONDecodeError included) or KeyError for text `dumps` did not write."""
    raw: dict[str, Any] | list[Any] | str | float | None = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("a checkpoint is a JSON object")
    asked = None if raw["asked"] is None else _from_entry(raw["asked"])
    if asked is not None and not isinstance(asked, ToolCalls):
        raise ValueError("the round in flight is not tool calls")
    done = {r.call_id: r for r in (_from_result(d) for d in raw["done"])}
    progress = Progress(tuple(_from_entry(e) for e in raw["entries"]), int(raw["rounds"]), int(raw["calls"]), asked,
                        done, tuple(int(i) for i in raw.get("steered", [])))
    return Checkpoint(_inbound(raw["inbound"]), int(raw["conversation_id"]), int(raw["said_id"]), raw["speaker_id"],
                      {k: SystemPrompt(v["stable"], v["moment"]) for k, v in raw["system"].items()}, progress,
                      frozenset(raw["started"]), frozenset(raw["offered"]), raw["phone"], raw.get("turn"),
                      None if raw.get("acting") is None else _from_acting(raw["acting"]), bool(raw.get("left", False)),
                      _pair(raw.get("carried")), _trigger(raw.get("escalated")), bool(raw.get("unreachable_told", False)),
                      _taint(raw.get("tainted")), bool(raw.get("changed", False)), _judged(raw.get("judged", {})),
                      float(raw.get("worked_s", 0.0)), int(raw.get("windows", 0)), int(raw.get("cut_off", 0)))


def addressed(text: str) -> tuple[Inbound, str | None] | None:
    """The message and screen token of a checkpoint `loads` may refuse, so its person can still be told the turn
    ended; None when even those cannot be read."""
    try:
        raw: dict[str, Any] | list[Any] | str | float | None = json.loads(text)
        if not isinstance(raw, dict):
            return None
        turn = raw.get("turn")
        return _inbound(raw["inbound"]), turn if isinstance(turn, str) else None
    except (ValueError, KeyError, TypeError):
        return None


def _inbound(raw: dict[str, Any]) -> Inbound:
    fields: dict[str, Any] = dict(raw)
    tools = fields.get("tools_only")
    fields["tools_only"] = None if tools is None else tuple(str(t) for t in tools)
    origin = fields.pop("taint", None)
    if origin is not None and origin not in get_args(Taint):
        raise ValueError("not a taint origin")
    made = _pair(fields.pop("made_in", None))
    moment = fields.pop("moment", None)
    return Inbound(**fields, taint=origin, made_in=made, moment=None if moment is None else _moment(moment))


def _moment(raw: dict[str, Any]) -> Moment:
    return Moment(str(raw["seed"]), raw["hour"], raw["others_home"], raw["since_heard_s"], raw["since_greeted_s"],
                  raw["since_spoke_s"])


def _judged(raw: Any) -> dict[str, Verdict]:
    loose: Any = raw
    if not isinstance(raw, dict):
        raise ValueError("not verdicts")
    try:
        return {str(i): checked(Verdict(v[0], v[1], str(v[2]))) for i, v in dict[Any, Any](loose).items()}
    except (JudgeUnavailable, IndexError, TypeError) as e:
        raise ValueError("not a verdict") from e


def _taint(raw: Any) -> str | None:
    if raw is not None and not isinstance(raw, str):
        raise ValueError("not a taint")
    return raw


def _trigger(raw: Any) -> Trigger | None:
    if raw is None:
        return None
    if raw not in ("a", "b"):
        raise ValueError("not an escalation trigger")
    return raw


def _pair(raw: Any) -> tuple[int, int] | None:
    if raw is None:
        return None
    talk, ask = raw
    return int(talk), int(ask)


def _acting(acting: Acting) -> dict[str, Any]:
    return {"action": acting.act.action, "facts": list(acting.act.facts), "hers": acting.hers,
            "started": acting.started}


def _from_acting(raw: dict[str, Any]) -> Acting:
    action = raw["action"]
    if action not in ("keep", "correct", "forget"):
        raise ValueError("not a memory act")
    return Acting(Act(action, tuple(int(f) for f in raw["facts"])), int(raw["hers"]), bool(raw["started"]))


def _entry(entry: Entry) -> dict[str, Any]:
    if isinstance(entry, Message):
        return {"message": {"author": entry.author, "text": entry.text}}
    if isinstance(entry, ToolCalls):
        return {"calls": [{"id": c.id, "name": c.name, "arguments": dict(c.arguments),
                           "provider_data": dict(c.provider_data)} for c in entry.calls]}
    return {"results": [_result(r) for r in entry.results]}


def _result(result: ToolResult) -> dict[str, Any]:
    return {"call_id": result.call_id, "content": result.content, "is_error": result.is_error,
            "outside": result.outside,
            "images": [{"media_type": i.media_type, "data": base64.b64encode(i.data).decode("ascii")}
                       for i in result.images]}


def _from_entry(raw: dict[str, Any]) -> Entry:
    if "message" in raw:
        return Message(raw["message"]["author"], raw["message"]["text"])
    if "calls" in raw:
        return ToolCalls(tuple(ToolCall(c["id"], c["name"], c["arguments"], c["provider_data"]) for c in raw["calls"]))
    return ToolResults(tuple(_from_result(r) for r in raw["results"]))


def _from_result(raw: dict[str, Any]) -> ToolResult:
    return ToolResult(raw["call_id"], raw["content"], bool(raw["is_error"]),
                      tuple(Image(i["media_type"], base64.b64decode(i["data"])) for i in raw.get("images", [])),
                      raw.get("outside"))
