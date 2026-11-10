"""What she did on a bench conversation, measured from fields, counts and clocks: never from her words. The measures
(`docs/decisions.md`, "Her behaviour is measured by what she did"):

M1 `first_answer_s`: per person turn, seconds to her next turn with `follows` false.
M2 `held`: per person turn, her held lines (turns with `follows` true) less the ones that told the model was unreachable.
M3 `empty_answers`: answers with `changes` 0 after which the person spoke again with no turn of hers between.
M4 `open_closes`: answers closed `deadline` or `stood`, or logged `answers=false`; `kept` and `broken`
   count those followed by a later turn of hers with `changes` above 0 before the person spoke, and by the person first.
M5 `deliverable`: the person turns from the first ask to a model run with exit 0 that they left standing (no
   undo of theirs before their next turn), and the wall time; None when never reached.
M6 `ended`: `respond.ended` by reason, and `failed`, the `respond.failed` count.

A join that cannot be made (a `respond.done` line for no answer) leaves that answer's `changes` unmeasured, never 0.
`measure` is pure over `Turn`, `Run` and `Event`; `parse_logfmt` reads the log lines and `main` reads Postgres (turns, runs,
a person's undos) for one conversation, with the log lines from files."""

import argparse
import asyncio
import shlex
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

OPEN = ("deadline", "stood")


@dataclass(frozen=True)
class Turn:
    id: int
    author: Literal["person", "ashley"]
    at: float
    follows: bool = False
    answers: int | None = None


@dataclass(frozen=True)
class Run:
    at: float
    exit_code: int | None
    piece_id: int | None


@dataclass(frozen=True)
class Event:
    """One log line: `name` is its `event`, `at` seconds since the epoch, `fields` every other key as text."""

    name: str
    at: float
    fields: dict[str, str]


@dataclass(frozen=True)
class Close:
    """One final answer, with what its `respond.done` said (None when no line joins it)."""

    turn: Turn
    changes: int | None
    closed: str | None
    answers: bool | None

    @property
    def is_open(self) -> bool:
        return self.closed in OPEN or self.answers is False


@dataclass(frozen=True)
class Measures:
    first_answer_s: dict[int, float | None]
    held: dict[int, int]
    empty_answers: list[int]
    open_closes: list[int]
    kept: int
    broken: int
    deliverable: tuple[int, float] | None
    ended: dict[str, int]
    failed: int
    unmeasured: int


def parse_logfmt(lines: Iterable[str]) -> list[Event]:
    """The events in logfmt `lines`, those with a `ts` and an `event` only."""
    found: list[Event] = []
    for line in lines:
        fields = _fields(line)
        if "ts" in fields and "event" in fields:
            at = datetime.fromisoformat(fields["ts"].replace("Z", "+00:00")).timestamp()
            found.append(Event(fields["event"], at, {k: v for k, v in fields.items() if k not in ("ts", "event")}))
    return found


def _fields(line: str) -> dict[str, str]:
    """The `key=value` pairs of a logfmt line; a line that does not tokenize has none."""
    try:
        return dict(t.split("=", 1) for t in shlex.split(line) if "=" in t)
    except ValueError:
        return {}


def closes(turns: Sequence[Turn], events: Sequence[Event]) -> list[Close]:
    """Each of her final answers (`follows` false) joined, in order, to the first `respond.done` line at or after it
    that no earlier answer took."""
    done = sorted((e for e in events if e.name == "respond.done"), key=lambda e: e.at)
    taken = 0
    out: list[Close] = []
    for t in sorted((t for t in turns if t.author == "ashley" and not t.follows), key=lambda t: t.at):
        while taken < len(done) and done[taken].at < t.at - 1:
            taken += 1
        line = done[taken] if taken < len(done) else None
        taken += line is not None
        out.append(Close(t, None, None, None) if line is None else Close(
            t, _int(line.fields.get("changes")), line.fields.get("closed"), _flag(line.fields.get("answers"))))
    return out


def measure(turns: Sequence[Turn], runs: Sequence[Run], events: Sequence[Event], undos: Sequence[float] = ()) -> Measures:
    """M1 to M6 over one bench conversation: `turns` in any order, the model `runs` of its bench, the log `events` of the
    conversation and the person's `undos` (when they undid something on the bench)."""
    ordered = sorted(turns, key=lambda t: (t.at, t.id))
    people = [t for t in ordered if t.author == "person"]
    made = closes(ordered, events)
    return Measures(
        first_answer_s=_first_answers(people, made), held=_held(people, ordered, events),
        empty_answers=[c.turn.id for c in made if c.changes == 0 and _spoke_again(c.turn, ordered)],
        open_closes=[c.turn.id for c in made if c.is_open], kept=_followed(made, ordered, True),
        broken=_followed(made, ordered, False), deliverable=_deliverable(people, runs, undos),
        ended=dict(Counter(e.fields.get("reason", "?") for e in events if e.name == "respond.ended")),
        failed=sum(e.name == "respond.failed" for e in events), unmeasured=sum(c.changes is None for c in made))


def _int(text: str | None) -> int | None:
    return int(text) if text is not None and text.isdigit() else None


def _flag(text: str | None) -> bool | None:
    return None if text not in ("true", "false") else text == "true"


def _first_answers(people: Sequence[Turn], made: Sequence[Close]) -> dict[int, float | None]:
    out: dict[int, float | None] = {}
    for p in people:
        later = [c.turn for c in made if c.turn.at >= p.at and (c.turn.answers in (None, p.id))]
        out[p.id] = min(t.at for t in later) - p.at if later else None
    return out


def _owner(at: float, people: Sequence[Turn]) -> int | None:
    before = [p.id for p in people if p.at <= at]
    return before[-1] if before else None


def _held(people: Sequence[Turn], ordered: Sequence[Turn], events: Sequence[Event]) -> dict[int, int]:
    count = {p.id: 0 for p in people}
    for t in ordered:
        owner = _owner(t.at, people)
        if t.author == "ashley" and t.follows and owner is not None:
            count[owner] += 1
    for e in events:
        owner = _owner(e.at, people)
        if e.name == "respond.ended" and e.fields.get("recovery", "").startswith("told") and owner is not None:
            count[owner] = max(0, count[owner] - 1)
    return count


def _next_person(after: Turn, ordered: Sequence[Turn]) -> Turn | None:
    return next((t for t in ordered if t.author == "person" and (t.at, t.id) > (after.at, after.id)), None)


def _spoke_again(answer: Turn, ordered: Sequence[Turn]) -> bool:
    nxt = _next_person(answer, ordered)
    if nxt is None:
        return False
    return not any(t.author == "ashley" and (answer.at, answer.id) < (t.at, t.id) < (nxt.at, nxt.id) for t in ordered)


def _followed(made: Sequence[Close], ordered: Sequence[Turn], kept: bool) -> int:
    count = 0
    for c in made:
        if not c.is_open:
            continue
        nxt = _next_person(c.turn, ordered)
        limit = (float("inf"), 0) if nxt is None else (nxt.at, nxt.id)
        acted = any(k.changes and (c.turn.at, c.turn.id) < (k.turn.at, k.turn.id) < limit for k in made)
        count += acted == kept
    return count


def _deliverable(people: Sequence[Turn], runs: Sequence[Run], undos: Sequence[float]) -> tuple[int, float] | None:
    if not people:
        return None
    for run in sorted(runs, key=lambda r: r.at):
        if run.exit_code == 0 and not _undone(run, people, undos):
            return sum(p.at <= run.at for p in people), run.at - people[0].at
    return None


def _undone(run: Run, people: Sequence[Turn], undos: Sequence[float]) -> bool:
    nxt = next((p.at for p in people if p.at > run.at), float("inf"))
    return any(run.at < u <= nxt for u in undos)


def render(m: Measures) -> str:
    seen = [s for s in m.first_answer_s.values() if s is not None]
    median = round(statistics.median(seen)) if seen else None
    reached = "never reached" if m.deliverable is None else f"{m.deliverable[0]} person turns, {m.deliverable[1]:.0f} s"
    return "\n".join([
        f"M1 first answer s per person turn: {[None if s is None else round(s) for s in m.first_answer_s.values()]}"
        f" median {median}",
        f"M2 held lines per person turn: {list(m.held.values())} (sum {sum(m.held.values())})",
        f"M3 empty answers: {len(m.empty_answers)} {m.empty_answers}",
        f"M4 open closes: {len(m.open_closes)} {m.open_closes}; kept {m.kept}, broken {m.broken}",
        f"M5 deliverable: {reached}", f"M6 ended {m.ended}, failed {m.failed}",
        f"answers with no respond.done line (changes unmeasured): {m.unmeasured}"])


async def _rows(url: str, conversation: int) -> tuple[list[Turn], list[Run], list[float]]:
    from psycopg import AsyncConnection
    async with await AsyncConnection.connect(url) as conn:
        cur = await conn.execute("SELECT id, author, extract(epoch FROM at), follows, answers FROM turns "
                                 "WHERE conversation_id = %s ORDER BY id", (conversation,))
        turns = [Turn(i, a, float(t), f, ans) for i, a, t, f, ans in await cur.fetchall()]
        cur = await conn.execute("SELECT extract(epoch FROM finished_at), exit_code, piece_id FROM code_runs "
                                 "WHERE conversation_id = %s AND finished_at IS NOT NULL", (conversation,))
        runs = [Run(float(t), c, p) for t, c, p in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT extract(epoch FROM c.at) FROM bench_commands c JOIN conversations v ON v.household_id = c.household_id "
            "WHERE v.id = %s AND c.person_id IS NOT NULL AND c.outcome = 'accepted' AND c.command->>'type' = 'undo'",
            (conversation,))
        return turns, runs, [float(t) for (t,) in await cur.fetchall()]


def main() -> None:
    """`python -m ashley.tools.bench_outcomes --database URL --conversation N LOGFILE...`: M1 to M6 for the conversation's
    turns and model runs in Postgres, and the logfmt lines in each LOGFILE (Loki exports of both sites)."""
    parser = argparse.ArgumentParser(prog="bench_outcomes")
    parser.add_argument("--database", required=True)
    parser.add_argument("--conversation", type=int, required=True)
    parser.add_argument("logs", nargs="*")
    args = parser.parse_args()
    turns, runs, undos = asyncio.run(_rows(args.database, args.conversation))
    lines = [line for path in args.logs for line in open(path).read().splitlines()]
    mine = [e for e in parse_logfmt(lines) if e.fields.get("conversation") in (None, str(args.conversation))]
    print(render(measure(turns, runs, mine, undos)))


if __name__ == "__main__":
    main()
