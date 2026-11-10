"""What she knew at a reply, and why: `respond.done` and `memory.apply` log lines of one conversation joined to the
fact rows their ids name. Pure: lines in, text out; the rows come from `report_queries` and the entry point is
`python -m ashley.memory report`. `render` writes fact text, so its output is for the operator's terminal, never a
log."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .model import Fact

_FIELD = re.compile(r'([A-Za-z_][\w.-]*)=("(?:[^"\\]|\\.)*"|[^\s"]*)')
_ESCAPE = re.compile(r"\\(.)")
_UNESCAPED = {"n": "\n", '"': '"', "\\": "\\"}
_OPS = ("add", "update", "invalidate", "forget", "noop", "deleted")


@dataclass(frozen=True)
class ReplySeen:
    """One `respond.done` line. `standing` and `recalled` are the fact ids offered from each tier in the order
    offered, None when the tier is unknown: memory was unreachable (`known_offered` True) or the line predates the
    fields (`known_offered` False). `used` are the offered ids the reply relied on; `used_unrecalled` how many ids it
    named that were not offered."""

    at: str
    kind: str
    medium: str
    speaker: str
    standing: tuple[int, ...] | None
    recalled: tuple[int, ...] | None
    used: tuple[int, ...]
    used_unrecalled: int
    known_offered: bool = True


@dataclass(frozen=True)
class WriteSeen:
    """One `memory.apply` line: the ids of the facts inserted, the count of each op, `deleted` the rows a `forget`
    removed, and the turn id the conversation was written through, None when the line did not say."""

    at: str
    inserted: tuple[int, ...]
    add: int
    update: int
    invalidate: int
    forget: int
    noop: int
    deleted: int
    written_through: int | None


def parse(line: str) -> dict[str, str] | None:
    """The fields of one logfmt line as `ashley.logs` writes it (`key=value`, or `key="value"` with `\\"`, `\\\\` and
    `\\n` escaped), the first of a repeated key winning; None when the line has no `event` field. Never raises."""
    fields: dict[str, str] = {}
    for key, raw in _FIELD.findall(line):
        if raw.startswith('"'):
            raw = _ESCAPE.sub(lambda m: _UNESCAPED.get(m.group(1), m.group(1)), raw[1:-1])
        fields.setdefault(key, raw)
    return fields if "event" in fields else None


def _ids(raw: str) -> tuple[int, ...]:
    """Raises ValueError for anything but comma-separated integers."""
    return tuple(int(part) for part in raw.split(",")) if raw else ()


def _tier(fields: Mapping[str, str], key: str) -> tuple[int, ...] | None:
    raw = fields.get(key)
    return None if raw is None or raw == "unavailable" else _ids(raw)


def _reply(fields: Mapping[str, str]) -> ReplySeen:
    return ReplySeen(fields.get("ts", ""), fields.get("kind", ""), fields.get("medium", ""),
                     fields.get("speaker", ""), _tier(fields, "standing_facts"), _tier(fields, "recalled_facts"),
                     _ids(fields.get("used_facts", "")), int(fields.get("used_unrecalled", "0")),
                     "standing_facts" in fields and "recalled_facts" in fields)


def _write(fields: Mapping[str, str]) -> WriteSeen:
    counts = {name: int(fields.get(name, "0")) for name in _OPS}
    through = fields.get("written_through")
    return WriteSeen(fields.get("ts", ""), _ids(fields.get("inserted", "")), **counts,
                     written_through=None if through is None else int(through))


def seen(lines: Iterable[str], conversation_id: int) -> tuple[tuple[ReplySeen, ...], tuple[WriteSeen, ...]]:
    """The replies (`respond.done`) and writes (`memory.apply`) logged for the conversation, each oldest first by
    time. A line repeated verbatim counts once; a line whose id lists are malformed is dropped."""
    replies: list[ReplySeen] = []
    writes: list[WriteSeen] = []
    for line in dict.fromkeys(line.rstrip("\r\n") for line in lines):
        fields = parse(line)
        if fields is None or fields.get("conversation") != str(conversation_id):
            continue
        try:
            if fields["event"] == "respond.done":
                replies.append(_reply(fields))
            elif fields["event"] == "memory.apply":
                writes.append(_write(fields))
        except ValueError:
            continue
    return (tuple(sorted(replies, key=lambda r: r.at)), tuple(sorted(writes, key=lambda w: w.at)))


def _fact(fact_id: int, facts: Mapping[int, Fact], used: str = "") -> str:
    fact = facts.get(fact_id)
    mark = f" [{used}]" if used else ""
    if fact is None:
        return f"  [{fact_id}] forgotten{mark}"
    state = ""
    if fact.valid_to is not None:
        state = f"; closed {fact.valid_to.isoformat()}"
        if fact.superseded_by is not None:
            state += f", replaced by [{fact.superseded_by}]"
    return (f'  [{fact_id}] "{fact.text}" ({fact.kind}, {fact.visibility}, '
            f'from conversation {fact.source_conversation_id}{state}){mark}')


def _tiers(reply: ReplySeen, facts: Mapping[int, Fact]) -> list[str]:
    used = set(reply.used)
    if reply.standing is None or reply.recalled is None:
        if reply.known_offered:
            return ["  memory unreachable"]
        return ["  offered facts not logged"] + [_fact(i, facts, "used") for i in reply.used]
    out = ["  standing:"] + [_fact(i, facts, "used" if i in used else "") for i in reply.standing]
    out += ["  recalled:"] + [_fact(i, facts, "used" if i in used else "") for i in reply.recalled]
    return out + [_fact(i, facts, "used, not offered")
                  for i in reply.used if i not in {*reply.standing, *reply.recalled}]


def _reply_block(reply: ReplySeen, facts: Mapping[int, Fact]) -> list[str]:
    head = f"{reply.at} reply: {reply.kind}, {reply.medium}, speaker {reply.speaker}"
    return [head, *_tiers(reply, facts), ""]


def _write_block(write: WriteSeen, facts: Mapping[int, Fact]) -> list[str]:
    ops = ", ".join(f"{name} {getattr(write, name)}" for name in _OPS)
    through = "" if write.written_through is None else f"; through turn {write.written_through}"
    return [f"{write.at} write: {ops}{through}", *[_fact(i, facts) for i in write.inserted], ""]


def render(conversation_id: int, replies: tuple[ReplySeen, ...], writes: tuple[WriteSeen, ...],
           facts: Mapping[int, Fact], writers: tuple[tuple[str, str, str, str], ...]) -> str:
    """The report for one conversation. Each reply, oldest first, lists the standing and recalled facts offered with
    their text, kind, visibility and source conversation; marks the ones it relied on `[used]`; says `closed <time>`
    and `replaced by [id]` of a fact no longer current, `forgotten` of an id with no row, and `used, not offered` of
    a used id neither tier offered. A reply whose tiers are unknown says `memory unreachable` or `offered facts not
    logged`, never an empty list. Then each write with the facts it inserted, and the writer model of each
    `memory_write` call from the spend ledger (`writers`: time, provider, model, outcome)."""
    if not replies and not writes:
        return f"Nothing found for conversation {conversation_id} in the lines given."
    out = [f"Conversation {conversation_id}", ""]
    for reply in replies:
        out += _reply_block(reply, facts)
    for write in writes:
        out += _write_block(write, facts)
    out += [f"{at} writer: {provider}/{model} ({outcome})" for at, provider, model, outcome in writers]
    return "\n".join(out).rstrip() + "\n"
