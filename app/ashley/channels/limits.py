"""How far one reply's tool loop may go and how many earlier turns it carries, per conversation kind: data
(`turns.json`) tuned from real use."""

import json
import math
from dataclasses import dataclass
from importlib import resources
from typing import Any, get_args

from ..conversations.model import Kind

KINDS: tuple[Kind, ...] = get_args(Kind)
_FIELDS = ("max_tool_rounds", "max_tool_result_chars", "recent_turns", "relevant_turns")
_LEAST = {"max_tool_rounds": 0, "max_tool_result_chars": 1, "recent_turns": 1, "relevant_turns": 0}
_SECONDS = ("hold_after_s", "deadline_s")
_RUNS = ("carried_runs", "run_script_chars", "run_output_chars")
_OPTIONAL = ("reply_chars", "escalates", "windows", "hand_off_after_s", "hand_off_after_rounds")


@dataclass(frozen=True)
class Limits:
    """`max_tool_rounds`: the most `ToolCalls` one reply may make before she must answer, >= 0.
    `max_tool_result_chars`: a tool result longer than this is cut to it before the model reads it, with a marker saying how much of how much it
    saw (`tools.cut`), >= 1.
    `recent_turns`: the most of the speaker's latest turns with her one reply carries, across conversations, >= 1.
    `relevant_turns`: the most older turns matching the message it carries beside them, >= 0.
    `hold_after_s`: on a turn that can hold, once it has run this long with no answer, her latest aside goes out as
    her holding line, > 0. `deadline_s`: once it has run this long, her next step must answer, with tool choice
    `none`, > 0. Both count from the turn's start and are checked before each step, `hold_after_s` also while a
    model step or a round's calls run; unset, neither ever passes.
    `carried_runs`: the most code runs, latest first, whose compact form her carried answers bring, >= 0.
    `run_script_chars`, `run_output_chars`: how much of a run's script, and of each of its output streams, that form
    keeps, >= 0. All three default to 0: no run is carried. A turn whose page moves to a bench takes `brainstorm`'s
    entry, a bench's talk's, from its next step on (`channels.landing`).
    `reply_chars`: the longest `Reply.text` a reply may have before the tool loop asks for it again shorter
    (`tool_loop.RESHORTENED` times at most), >= 0; 0, the default, sets no limit.
    `windows`: how many fresh windows (`hold_after_s` and `deadline_s` counted again, work so far kept) a turn still
    calling tools takes at `deadline_s` before it must close, >= 0; 0, the default, takes none.
    `escalates`: whether a turn of this kind that reaches `max_tool_rounds` or `deadline_s` with no answer, or whose
    reply sets `Reply.escalate`, is run again on the stronger route (`channels.escalation`); false, the default.
    `hand_off_after_s`, `hand_off_after_rounds`: a turn that offers `bench_hand_off` and has run this many seconds
    (of its window), or made this many rounds, is told once that handing the work off is the way (`channels.hand_off`);
    unset (0), never."""

    max_tool_rounds: int
    max_tool_result_chars: int
    recent_turns: int
    relevant_turns: int
    hold_after_s: float = math.inf
    deadline_s: float = math.inf
    carried_runs: int = 0
    run_script_chars: int = 0
    run_output_chars: int = 0
    reply_chars: int = 0
    escalates: bool = False
    windows: int = 0
    hand_off_after_s: int = 0
    hand_off_after_rounds: int = 0


def smallest_result_chars(limits: dict[Kind, Limits]) -> int:
    """The least `max_tool_result_chars` of any kind: what a result must fit to be read whole in every conversation."""
    return min(l.max_tool_result_chars for l in limits.values())


def load() -> dict[Kind, Limits]:
    """The limits shipped in `turns.json` beside this module. Raises ValueError when a kind is missing or a limit is
    out of range."""
    return parse(json.loads(resources.files("ashley.channels").joinpath("turns.json").read_text()))


def parse(data: object) -> dict[Kind, Limits]:
    """Limits from JSON already parsed: `{"<kind>": {"max_tool_rounds": n, "max_tool_result_chars": n,
    "recent_turns": n, "relevant_turns": n, "hold_after_s": s, "deadline_s": s, "carried_runs": n,
    "run_script_chars": n, "run_output_chars": n, "reply_chars": n, "windows": n}, ...}`, one entry per kind and no
    others, each entry with every key but `reply_chars`, `escalates` and `windows`, which may be left out. Raises ValueError naming what is wrong otherwise."""
    entries = _object(data)
    if entries is None:
        raise ValueError("turn limits are an object with one entry per kind")
    missing = [k for k in KINDS if k not in entries]
    extra = sorted(set(entries) - set(KINDS))
    if missing or extra:
        raise ValueError(f"turn limit kinds: missing {missing}, unknown {extra}")
    return {kind: _limits(kind, entries[kind]) for kind in KINDS}


def _object(value: object) -> dict[str, object] | None:
    raw: Any = value
    if not hasattr(raw, "keys") or not all(type(key) is str for key in raw.keys()):
        return None
    return dict[str, object](raw)


def _limits(kind: str, entry: object) -> Limits:
    fields = _object(entry)
    required = {*_FIELDS, *_SECONDS, *_RUNS}
    if fields is None or not required <= set(fields) <= required | set(_OPTIONAL):
        raise ValueError(f"{kind}: expected exactly {', '.join((*_FIELDS, *_SECONDS, *_RUNS))}, and `reply_chars`, `escalates`, `windows` and the `hand_off_after_` pair if any")
    return Limits(*(_count(kind, name, fields[name], _LEAST[name]) for name in _FIELDS),
                  *(_seconds(kind, name, fields[name]) for name in _SECONDS),
                  *(_count(kind, name, fields[name], 0) for name in _RUNS),
                  reply_chars=_count(kind, "reply_chars", fields["reply_chars"], 0) if "reply_chars" in fields else 0,
                  escalates=_flag(kind, fields["escalates"]) if "escalates" in fields else False,
                  windows=_count(kind, "windows", fields["windows"], 0) if "windows" in fields else 0,
                  hand_off_after_s=_count(kind, "hand_off_after_s", fields["hand_off_after_s"], 0) if "hand_off_after_s" in fields else 0,
                  hand_off_after_rounds=_count(kind, "hand_off_after_rounds", fields["hand_off_after_rounds"], 0) if "hand_off_after_rounds" in fields else 0)


def _seconds(kind: str, name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 < value < math.inf:
        raise ValueError(f"{kind}.{name}: expected a number of seconds above 0")
    return float(value)


def _flag(kind: str, value: object) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{kind}.escalates: expected true or false")
    return value


def _count(kind: str, name: str, value: object, least: int) -> int:
    if type(value) is not int or value < least:
        raise ValueError(f"{kind}.{name}: expected an integer >= {least}")
    return value
