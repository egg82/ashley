"""Support for the blind bench-jobs suite, written from `spec.txt` (sections 4 and 5, and "Resolved by the orchestrator")
alone. EVERY reference to an implementation name lives in this module or its stand-ins (`bjb_fakes`), so a reconciler rewires names here and leaves
the assertions alone. The guesses (module paths, field names, argument shapes) are marked `GUESS` and listed in
`~/scratch/ashley/handoff/blind/blind-notes.txt`.

The implementation did not exist when this was written, so the imports sit behind a guard: when one is missing the
`conftest` skips every test that needs it, naming the missing import, and the suite still collects."""

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg
from ashley import services
from ashley.channels.model import Inbound
from ashley.channels.turn_tools import sources
from ashley.channels.wake import watch_turn
from ashley.connections.connections import Connections
from ashley.db.pool import PoolDatabase
from ashley.files.memory import MemoryStore
from ashley.files.store import ObjectStore
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Access
from ashley.inference.inference import Inference
from ashley.inference.model import ToolCall, ToolResult
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Wakes, WatchWake
from ashley.tools.tools import Tools, ToolsUnavailable
from ashley.watches import job as watches_job
from ashley.watches.postgres import PostgresWatches
from ashley.watches.registry import KINDS
from ashley.watches.watches import NullWatches, Watches
from ashley.workshop import stored_file
from ashley.workshop.bench_file import add_file
from ashley.workshop.commands import Add, Archive, Remove
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.workshop import Workshop
from bjb_fakes import (HANG as HANG, ROOT as ROOT, FakeBridge as FakeBridge, Scripted as Scripted,
                       calls_of as calls_of, everything_shown as everything_shown, finished as finished,
                       first_user_message as first_user_message, out_file as out_file,
                       results_seen as results_seen)
from bench_run_support import Box, World as RunWorld, world as run_world
from contract.conversations_support import household, person, run as run_bounded, scalar
from files_support import PNG
from money_support import HeldConnections

from ashley.channels.bench_job.runner import BenchJobRunner
from ashley.errands import jobs_config
from ashley.errands.bench_job_model import Ending, Job, Named, NewJob, Outcome, Worker
from ashley.errands.bench_jobs import BenchJobs
from ashley.errands.bench_jobs_postgres import PostgresBenchJobs
from ashley.tools import bench_agent as bench_agent, bench_session as bench_session
from ashley.tools.bench_jobs import BenchJobTools
from ashley.tools.job_scope import JobScope

PIN = "0" * 64
ACCESS = Access("https://127.0.0.1:7843", PIN, "token", 1)
BRIDGE_URL = f"https://127.0.0.1:7843#sha256={PIN}"
MARK_TITLE = "TITLE-MARK-zq41"
MARK_BODY = "BODY-MARK-7f3k"
MARK_BRIEF = "BRIEF-MARK-p92d"
JOB_PIECE_KIND = "job"
Json = dict[str, Any]


def run(scenario: Coroutine[Any, Any, None], limit: float = 25.0) -> None:
    run_bounded(scenario, limit)


# --- config ------------------------------------------------------------------------------------------------------


def cfg() -> Any:
    """The shipped `jobs.json` as `jobs_config` loads it."""
    return jobs_config.CONFIG


def limit(name: str, worker: str | None = None) -> int:
    got = getattr(cfg(), name)
    return int(got if worker is None else got[worker])


# --- shapes guessed from the interface section ---------------------------------------------------------------------


def named(piece_id: int, run_files: bool = False) -> Any:
    return Named(piece_id, run_files)


def new_job(w: "World", worker: Worker = "agent", title: str = "Gate", brief: str = "Build the gate.",
            pieces: Sequence[Any] = (), piece_id: int = 1, turn: int | None = None, bench: int | None = None) -> Any:
    return NewJob(household=w.owner.household_id, person=w.owner.person_id, bench=bench or w.bench,
                  conversation=w.conversation, turn=turn or w.turn, worker=worker, title=title, brief=brief,
                  pieces=tuple(pieces), piece_id=piece_id)


def outcome(state: Ending, reason: str | None = None, summary: str | None = None, outputs: Sequence[int] = (),
            refused: int = 0) -> Any:
    return Outcome(state=state, reason=reason, summary=summary, outputs=tuple(outputs), refused=refused)


def scope(inner: Tools, job: Any) -> Tools:
    return JobScope(inner, job)


# --- results of a tool call -----------------------------------------------------------------------------------------


def payload(result: ToolResult) -> Json:
    assert not result.is_error, result.content
    body: Json = json.loads(result.content)
    assert isinstance(body, dict)
    return body


def reason(result: ToolResult) -> str:
    """The reason code of a failed call: what precedes the first colon."""
    assert result.is_error, result.content
    return result.content.split(":", 1)[0].strip()


def call(name: str, /, **arguments: object) -> ToolCall:
    return ToolCall(f"c-{name}", name, dict(arguments))


# --- the world ----------------------------------------------------------------------------------------------------------


@dataclass
class World:
    url: str
    db: PoolDatabase
    owner: Owner
    mate: Owner
    conversation: int
    turn: int
    bench: int
    other_bench: int
    foreign_bench: int
    jobs: BenchJobs
    bridge: FakeBridge
    model: Scripted
    store: MemoryStore
    box: Box
    connections: HeldConnections
    ran: RunWorld
    runners: list[Any] = field(default_factory=list[Any])

    def new_turn(self) -> int:
        return int(scalar(self.url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, "
                                    "visibility) VALUES (%s, %s, 'person', %s, 'go', 'shared') RETURNING id",
                          (self.conversation, self.owner.household_id, self.owner.person_id)))

    def tools(self, can_code: bool = False, bench: int | None = None, turn: int | None = None) -> Any:
        return BenchJobTools(self.owner.household_id, self.owner.person_id, bench or self.bench,
                             (self.conversation, turn or self.turn), can_code)

    def runner(self) -> Any:
        made = BenchJobRunner()
        self.runners.append(made)
        return made

    async def piece(self, kind: str, title: str = "p", body: str = "x", bench: int | None = None) -> int:
        got = await services.get(Workshop).apply(self.owner, bench or self.bench,
                                                 Add(By(self.owner.person_id), kind, Text(title, body), "medium"))
        assert got.outcome == "accepted" and got.piece_id is not None, got
        return got.piece_id

    async def file_piece(self, data: bytes = PNG, name: str = "pic.png", declared: str = "image/png",
                         bench: int | None = None) -> int:
        from ashley.workshop import rules as workshop_rules
        _, got = await add_file(self.owner, bench or self.bench, By(self.owner.person_id), data, name, declared,
                                workshop_rules.load())
        assert got.piece_id is not None, got
        return got.piece_id

    async def huge_piece(self, size: int, name: str = "big.zip") -> int:
        """A file piece whose stored body says it is `size` bytes (the bytes themselves are not held)."""
        body = stored_file.body_of(stored_file.StoredFile("a" * 64, size, "application/zip", name))
        return await self.piece("file", name, body)

    async def shelve(self, piece: int, bench: int | None = None) -> None:
        got = await services.get(Workshop).apply(self.owner, bench or self.bench, Archive(By(self.owner.person_id), piece))
        assert got.outcome == "accepted", got

    async def remove(self, piece: int, bench: int | None = None) -> None:
        got = await services.get(Workshop).apply(self.owner, bench or self.bench, Remove(By(self.owner.person_id), piece))
        assert got.outcome == "accepted", got

    async def pieces(self, bench: int | None = None) -> dict[int, Any]:
        view = await services.get(Workshop).read(self.owner, bench or self.bench)
        return {p.id: p for p in view.pieces}

    async def hand_off(self, *specs: Json, can_code: bool = False, turn: int | None = None,
                       bench: int | None = None) -> ToolResult:
        return await self.tools(can_code, bench, turn).call(call("bench_hand_off", jobs=list(specs)))

    async def start(self, *jobs: Any) -> tuple[int, tuple[int, ...]]:
        got = await self.jobs.start_group(tuple(jobs))
        return int(got[0]), tuple(int(i) for i in got[1])

    async def started(self, worker: Worker = "agent", **kw: Any) -> int:
        _, ids = await self.start(new_job(self, worker, **kw))
        return ids[0]

    async def claimed(self, worker: Worker = "agent") -> Job:
        got = await self.jobs.claim(worker, cfg().claim_s)
        assert got is not None, "nothing was due to claim"
        return got

    async def ticks(self, n: int = 8) -> None:
        runner = self.runners[-1] if self.runners else self.runner()
        for _ in range(n):
            await runner.tick()
            await asyncio.sleep(0)
        await asyncio.sleep(0.3)  # a task a tick started finishes by its own awaits: the row, then its piece

    async def drain(self) -> None:
        for _ in range(5):
            await asyncio.sleep(0)

    def commit_sql(self, query: str, params: tuple[object, ...] = ()) -> None:
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(query.encode(), params)


def spec(worker: str = "agent", title: str = "Gate", brief: str = "Build the gate.", pieces: Sequence[Any] = ()) -> Json:
    """One job of a `bench_hand_off` call; a piece is an id or an (id, run_files) pair."""
    shaped = [{"id": p, "run_files": False} if isinstance(p, int) else {"id": p[0], "run_files": p[1]} for p in pieces]
    return {"worker": worker, "title": title, "brief": brief, "pieces": shaped}


@asynccontextmanager
async def opened(url: str, connected: bool = True) -> AsyncGenerator[World]:
    home = household(url, "home")
    owner = Owner(home, person(url, home, "alana"))
    mate = Owner(home, person(url, home, "sam"))
    conversation = int(scalar(url, "INSERT INTO conversations (household_id, kind) VALUES (%s, 'brainstorm') RETURNING id",
                              (home,)))
    turn = int(scalar(url, "INSERT INTO turns (conversation_id, household_id, author, speaker_id, text, visibility) "
                           "VALUES (%s, %s, 'person', %s, 'go', 'shared') RETURNING id",
                      (conversation, home, owner.person_id)))
    async with run_world(url) as ran:
        shop = services.get(Workshop)
        bench = (await shop.open(owner, "bench")).id
        other = (await shop.open(owner, "other")).id
        foreign = (await shop.open(mate, "sams")).id
        jobs, bridge, model, store, connections = PostgresBenchJobs(ran.database), FakeBridge(), Scripted(), \
            MemoryStore(), HeldConnections()
        if connected:
            connections.connect(home, BRIDGE_URL, "token", "herdr", owner.person_id)
        wired: tuple[tuple[Any, Any], ...] = ((BenchJobs, jobs), (Bridge, bridge), (Inference, model),
                                              (ObjectStore, store), (Connections, connections),
                                              (Watches, PostgresWatches(ran.database)),
                                              (Wakes, PostgresWakes(ran.database)))
        for interface, impl in wired:
            services.register(interface, impl)
        made = World(url, ran.database, owner, mate, conversation, turn, bench, other, foreign, jobs, bridge, model,
                     store, ran.box, connections, ran)
        try:
            yield made
        finally:
            for r in made.runners:
                stop = getattr(r, "stop", None)
                if stop is not None:
                    await stop()
            for interface, _ in wired:
                services.unregister(interface)


def scenario(url: str, body: Callable[[World], Coroutine[Any, Any, None]], connected: bool = True) -> None:
    async def go() -> None:
        async with opened(url, connected) as w:
            await body(w)

    run(go())


# --- raw rows ------------------------------------------------------------------------------------------------------------


def row(url: str, job: int) -> Json:
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.execute("SELECT * FROM bench_jobs WHERE id = %s", (job,))
        names = [c.name for c in cur.description or ()]
        found = cur.fetchone()
    assert found is not None, f"no job {job}"
    return dict(zip(names, found, strict=True))


def job_count(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM bench_jobs"))


def state_of(url: str, job: int) -> str:
    return str(scalar(url, "SELECT state FROM bench_jobs WHERE id = %s", (job,)))


def age(url: str, job: int, column: str, seconds: float) -> None:
    assert column in ("claimed_at", "deadline_at", "created_at")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"UPDATE bench_jobs SET {column} = {column} - make_interval(secs => %s) WHERE id = %s".encode(),
                     (seconds, job))


def expire(url: str, job: int, column: str = "deadline_at") -> None:
    """Make `column` an hour ago, whatever it was (a deadline not yet set becomes one that has passed)."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"UPDATE bench_jobs SET {column} = now() - interval '1 hour' WHERE id = %s".encode(), (job,))


def watch_rows(url: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute("SELECT id, kind, target, armed_by, bench_id, track, state FROM watches "
                            "WHERE kind = 'bench_job' ORDER BY id").fetchall()


def watch_due_now(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE watches SET next_check_at = now() - interval '1 second'")


def job_pieces(pieces: dict[int, Any]) -> list[Any]:
    return [p for p in pieces.values() if p.kind == JOB_PIECE_KIND]


def job_body(piece: Any) -> Json:
    body: Json = json.loads(piece.text.body)
    assert isinstance(body, dict)
    return body


def inputs_to(w: World, session: str) -> dict[str, bytes]:
    return w.bridge.inbox.get(session, {})


# --- a bench turn, what it is offered, and the woken turn ----------------------------------------------------------------


def bench_inbound(w: World, **changes: Any) -> Inbound:
    """The owner's talk on their own bench: a reply that reaches them alone, asked for by them."""
    base: dict[str, Any] = dict(household_id=w.owner.household_id, thread=f"bench:{w.bench}", text="go on", kind="brainstorm",
                                medium="text", audience="owner", speaker_id=w.owner.person_id, shared=False, place=None,
                                channel="web", bench_id=w.bench, later=True, later_by="turn")
    return Inbound(**{**base, **changes})


async def offered_names(w: World, inbound: Inbound) -> set[str]:
    """Every tool name any source of this turn offers."""
    found: set[str] = set()
    for tools in sources(inbound, None, w.conversation, None, (w.conversation, w.turn)).values():
        try:
            found |= {s.name for s in (await tools.catalogue()).specs}
        except ToolsUnavailable:
            continue
    return found


def watches_down() -> Watches:
    return NullWatches()


async def watch_tick(w: World) -> None:
    """Every watch is due, and the watches job runs one tick over the registered kinds."""
    watch_due_now(w.url)
    await watches_job.tick()


def wake_count(url: str) -> int:
    return int(scalar(url, "SELECT count(*) FROM wakes WHERE kind = 'watch'"))


def settle_wakes(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE wakes SET settled_at = now(), outcome = 'turn' WHERE settled_at IS NULL")


async def woken(w: World, on_bench: bool = True) -> list[Inbound]:
    """The turns the unsettled watch wakes would start, built as the app builds them."""
    found: list[Inbound] = []
    for due in await services.get(Wakes).due(50):
        assert isinstance(due.wake, WatchWake)
        watch = await services.get(Watches).get(due.wake.watch_id)
        assert watch is not None
        found.append(watch_turn.inbound(due.id, watch, due.wake, on_bench, await KINDS.get(watch.kind).detail(watch)))
    return found


def woken_text(turn: Inbound) -> str:
    return turn.text + "\n" + (turn.note or "")


def watch_kind_outside() -> bool:
    return bool(KINDS.get("bench_job").outside)
