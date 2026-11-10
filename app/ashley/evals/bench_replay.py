"""The bench replay: a captured bench conversation (`bench_replay_snapshot`) asked again, ask by ask, through her real
turn loop (`channels.respond`), on a bench rebuilt in a scratch database from its command log, and scored by mechanics
(`bench_replay_measures`), never by how her replies read (`docs/decisions.md`, "Her behaviour is measured by what she
did"). It is the bench-act eval's multi-turn form: where bench-act grades one turn on a frozen bench, here the bench
changes as she works, her runs really run, and the person's own changes between asks (a photo added, a run) are made
at the point they were made.

Replay: the bench is rebuilt from the commands before the first ask (the last run of each piece executed, the rest only
logged), the turns said on its thread before are stored with their ages kept, and then each ask in order: the person's
own commands since the last ask, then the person's message (`on_bench`), or for a turn the bench's changes started, the
reaction turn the wake sweep would start (`bench_react_turn`); each waits for her final answer.

Records (`records`): the production conversation measured the same way. Every logged command is applied again in
order and the conversation's runs are executed again (production keeps only a bench's latest runs, so their reports
are reproduced, by the same code at the same version with the same inputs); turns, times and looks are the captured
ones.

Both grade her final answers with the grader (`bench_replay_grader`), whose fields are reported apart from the
records', and report the bench outcome measures (`tools.bench_outcomes.measure`, M1 to M6) over the same turns and runs.
Logs `eval.bench_replay` once per run: mode, asks, failed asks, runs and duration_ms. Never a turn's text."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

from .. import logs, services
from ..channels.model import on_bench
from ..channels import resume
from ..channels.respond import RespondError, respond
from ..channels.wake import bench_react_turn
from ..db.database import Database
from ..tools import bench_outcomes as outcomes
from ..tools import bench_replay_world as world
from ..tools.bench_replay_world import Finished
from . import bench_replay_rows as rows
from . import bench_replay_seed as seed
from .bench_replay_grader import Verdict
from .bench_replay_measures import AskMeasures, Record, bodies_at, form_before_model, items, kinds, measure
from .bench_replay_snapshot import Command, Said, Snapshot

log = logging.getLogger("ashley.evals")
Grader = Callable[[str, str, Sequence[str]], Awaitable[Verdict | None]]
GRADED = ("asks_to_look", "asked_form", "claimed_unbacked", "measurement_reasks")
"""The measures that read the grader's verdict; every other is read from records."""


@dataclass(frozen=True)
class Options:
    records: bool = False
    scope_kinds: tuple[str, ...] = ("model",)
    answer_timeout_s: float = 1800.0
    poll_s: float = 1.0


@dataclass(frozen=True)
class Result:
    mode: str
    asks: list[AskMeasures]
    form_before_model: bool | None
    outcomes: dict[str, Any]
    seconds: float
    failed: dict[int, str] = field(default_factory=dict[int, str])
    diverged: dict[int, str] = field(default_factory=dict[int, str])
    cost_usd: float | None = None
    grader_cost_usd: float | None = None
    runs: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    captured: dict[int, int] = field(default_factory=dict[int, int])
    """Each ask's turn id here to the captured turn it asked again."""


@dataclass
class _Bench:
    household: int
    person: int
    bench: int
    zone: str
    diverged: dict[int, str] = field(default_factory=dict[int, str])
    asked: dict[int, int] = field(default_factory=dict[int, int])

    async def apply(self, command: Command, execute: bool, current: bool = False) -> None:
        got = await world.apply(self.household, self.person, self.bench, command.command, command.by_person,
                                command.outside, execute, current)
        if got != command.outcome:
            self.diverged[command.seq] = f"{command.outcome}->{got}"


async def replay(snapshot: Snapshot, files: dict[str, bytes], database_url: str, grader: Grader,
                 options: Options = Options(), events: Sequence[str] = ()) -> Result:
    """Run the replay, or measure the records when `options.records`, on the services wired to the scratch database
    `database_url`. `events` are the captured log lines of the production conversation, read in records mode only."""
    started = time.monotonic()
    household, person = seed.seat(database_url, snapshot.zone, snapshot.person)
    world.install_files(household, files)
    world.no_screens()
    recording = world.record_runs()
    bench = _Bench(household, person, await world.open_bench(household, person, snapshot.bench_title, snapshot.work),
                   snapshot.zone)
    lines = _Lines()
    try:
        record, failed = await (_records(snapshot, bench, recording) if options.records
                                else _replayed(snapshot, bench, recording, options))
    finally:
        lines.close()
    record = await _graded(record, grader)
    asks = measure(record, options.scope_kinds)
    result = Result("records" if options.records else "replay", asks, form_before_model(record),
                    _outcomes(record, events if options.records else lines.lines), round(time.monotonic() - started, 1),
                    failed, bench.diverged, *await _cost(), [_run(f) for f in recording.finished],
                    {a.turn_id: a.turn_id for a in asks} if options.records else bench.asked)
    logs.info(log, "eval.bench_replay", mode=result.mode, asks=len(asks), failed=len(failed),
              runs=len(record.runs), duration_ms=int(result.seconds * 1000))
    return result


async def _records(snapshot: Snapshot, bench: _Bench, recording: world.RecordingRuns) -> tuple[Record, dict[int, str]]:
    first = snapshot.first_at()
    for c in snapshot.commands:
        await bench.apply(c, execute=c.at >= first)
    said = tuple(t for t in snapshot.turns if t.conversation_id == snapshot.conversation_id)
    return Record(said, snapshot.commands, snapshot.looks, _by_seq(recording.finished)), {}


async def _replayed(snapshot: Snapshot, bench: _Bench, recording: world.RecordingRuns,
                    options: Options) -> tuple[Record, dict[int, str]]:
    first = snapshot.first_at()
    before = [c for c in snapshot.commands if c.at < first]
    last_runs = {_last_run(before, piece) for piece in {c.command.get("piece_id") for c in before}}
    for c in before:
        await bench.apply(c, execute=c.seq in last_runs)
    await seed.turns(bench.household, bench.person, bench.bench, snapshot.before(), time.time() - first)
    began = await _now()
    resuming = asyncio.create_task(resume.run())
    try:
        failed = await _asked(snapshot, bench, options)
    finally:
        resuming.cancel()
    return await _recorded(bench, began, recording), failed


async def _asked(snapshot: Snapshot, bench: _Bench, options: Options) -> dict[int, str]:
    """Each ask in order, the person's own commands since the last one first; why each that got no answer got none.
    The `inflight` singleton's sweep runs meanwhile, as it does beside the app, so a turn whose model call failed and
    was kept is finished from its checkpoint."""
    failed: dict[int, str] = {}
    theirs = [c for c in snapshot.commands if c.by_person and c.at >= snapshot.first_at()]
    for ask in snapshot.asks():
        for c in [c for c in theirs if c.at < ask.at]:
            await bench.apply(c, execute=True, current=True)
        theirs = [c for c in theirs if c.at >= ask.at]
        why = await _ask(ask, bench, options)
        if why is not None:
            failed[ask.id] = why
    return failed


def _last_run(commands: Sequence[Command], piece: object) -> int:
    runs = [c.seq for c in commands if c.command.get("type") == "run" and c.command.get("piece_id") == piece]
    return runs[-1] if runs else -1


async def _ask(ask: Said, bench: _Bench, options: Options) -> str | None:
    """Ask `ask` and wait for her final answer; why it got none, or None."""
    unseen = None
    if ask.author == "household":
        unseen = await world.unseen(bench.household, bench.bench)
        if unseen is None:
            return "no_changes"
    inbound = (on_bench(bench.household, bench.person, bench.bench, ask.text) if unseen is None
               else bench_react_turn.inbound(unseen, ZoneInfo(bench.zone)))
    try:
        out = await respond(inbound)
    except RespondError as e:
        return type(e).__name__
    finally:
        if unseen is not None:
            await world.reacted(unseen)
    said = await _said(bench)
    bench.asked[said] = ask.id
    return await _answered(said, options) if out.follows else None


async def _said(bench: _Bench) -> int:
    async with services.get(Database).connection() as conn:
        row = await (await conn.execute(
            "SELECT max(t.id) FROM turns t JOIN conversations c ON c.id = t.conversation_id "
            "WHERE c.thread = %s AND t.author <> 'ashley'", (f"bench:{bench.bench}",))).fetchone()
    assert row is not None and row[0] is not None
    return int(row[0])


async def _answered(said: int, options: Options) -> str | None:
    """Wait for her final answer to turn `said`: None once it is stored; `unanswered` when its work is gone without one,
    `timeout` past the options' wait."""
    deadline, idle = time.monotonic() + options.answer_timeout_s, 0
    while time.monotonic() < deadline:
        async with services.get(Database).connection() as conn:
            got = await (await conn.execute(
                "SELECT (SELECT count(*) FROM turns WHERE answers = %s AND author = 'ashley' AND NOT follows), "
                "(SELECT count(*) FROM turn_work WHERE said_id = %s)", (said, said))).fetchone()
        assert got is not None
        if got[0]:
            return None
        idle = idle + 1 if not got[1] else 0
        if idle > 5:
            return "unanswered"
        await asyncio.sleep(options.poll_s)
    return "timeout"


async def _now() -> int:
    """The newest conversation id so far; the replay's conversations come after it."""
    async with services.get(Database).connection() as conn:
        row = await (await conn.execute("SELECT coalesce(max(id), 0) FROM conversations")).fetchone()
    assert row is not None
    return int(row[0])


async def _recorded(bench: _Bench, began: int, recording: world.RecordingRuns) -> Record:
    async with services.get(Database).connection() as conn:
        commands = await rows.commands(conn, bench.bench)
        said = await rows.turns(conn, bench.household, bench.bench, began + 1, 2 ** 62)
        looked = await rows.looks(conn, bench.bench, began + 1)
    return Record(said, commands, looked, _by_seq(recording.finished))


def _run(finished: Finished) -> dict[str, Any]:
    """A run as the result lists it: its seq, piece and version, how it ended and its report's counts."""
    return {k: v for k, v in asdict(finished).items() if k not in ("started", "finished", "turn_id")}


def _by_seq(finished: Sequence[Finished]) -> dict[int, Finished]:
    return {f.seq: f for f in finished}


async def _graded(record: Record, grader: Grader) -> Record:
    piece_kinds = kinds(record.commands)
    asked = {t.id: t for t in record.turns if t.author != "ashley"}
    verdicts: dict[int, Verdict] = {}
    for t in record.turns:
        if t.author == "ashley" and not t.follows and t.answers in asked:
            names = [n for pid, body in bodies_at(record.commands, t.at).items()
                     if piece_kinds.get(pid) == "measurements" for n in items(body)]
            got = await grader(asked[t.answers].text, t.text, names)
            if got is not None:
                verdicts[t.id] = got
    return Record(record.turns, record.commands, record.looks, record.runs, verdicts)


def _outcomes(record: Record, lines: Sequence[str]) -> dict[str, Any]:
    turns = [outcomes.Turn(t.id, "ashley" if t.author == "ashley" else "person", t.at, t.follows, t.answers)
             for t in record.turns]
    ran = [outcomes.Run(c.at, record.runs[c.seq].exit_code, int(c.command["piece_id"])) for c in record.commands
           if c.command.get("type") == "run" and c.seq in record.runs and c.at >= (turns[0].at if turns else 0)]
    return asdict(outcomes.measure(turns, ran, outcomes.parse_logfmt(lines)))


async def _cost() -> tuple[float | None, float | None]:
    async with services.get(Database).connection() as conn:
        row = await (await conn.execute(
            "SELECT sum(cost_usd), sum(cost_usd) FILTER (WHERE task = 'eval_judge') FROM inference_calls")).fetchone()
    return (None, None) if row is None else (_float(row[0]), _float(row[1]))


def _float(value: object) -> float | None:
    return None if value is None else round(float(str(value)), 4)


class _Lines(logging.Handler):
    """The log lines the process writes while it is attached, as Loki would hold them."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.setFormatter(logs.Logfmt())
        logging.getLogger("ashley").addHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    def close(self) -> None:
        logging.getLogger("ashley").removeHandler(self)
        super().close()


def to_json(result: Result) -> dict[str, Any]:
    """The result as JSON-ready data, with which source each measure reads."""
    basis = {k: "grader" if k in GRADED else "records" for k in AskMeasures.__dataclass_fields__ if k not in ("turn_id", "author", "reask_basis")}
    return {**asdict(result), "basis": basis}
