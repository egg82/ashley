"""The world for the Claude Code session watch (the `claude_session` kind and the watches job): a real database; the
app's Bridge port answering from the real bridge program over the captured `herdr agent list` (so a session's wire shape is what the bridge sends), with each session's
status and `state_change_seq` set by the test; a person's herdr connection; browsers subscribed; and the services the
turn loop reaches (`bench_reacts_support.world`)."""

import asyncio
import json
import tempfile
from collections import Counter
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ashley import services
from ashley.channels.push.subscriptions import Subscription, Subscriptions
from ashley.connections.connections import Connections
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.herdr import wire
from ashley.herdr.bridge import Bridge
from ashley.herdr.model import Access, BridgeFailed, OutFile, Screen, Session, SessionList, Status, Whoami
from ashley.senses.postgres_wakes import PostgresWakes
from ashley.senses.wakes import Wakes
from ashley.watches import job
from ashley.watches.claude_session import NAME, items_of
from ashley.watches.config import CONFIG
from ashley.watches.model import Arm, Armed, ArmedBy, Check, Counts, Watch
from ashley.watches.postgres import PostgresWatches
from ashley.watches.watches import Watches, WatchesUnavailable
from ashley.live.postgres_screens import PostgresScreens
from ashley.live.screens import Screens
from herdr_bridge.runner import Outcome
from herdr_bridge_support import THROWAWAY, Bridge as BridgeProgram, FakeHerdr, captured
from bench_reacts_support import World, world as bench_world
from contract.conversations_support import scalar
from money_support import HeldConnections
from push_support import FakeSubscriptions, browser

PIN = "0" * 64
SESSION = THROWAWAY


def listing_with(states: Mapping[str, tuple[str, int]]) -> Outcome:
    """The captured `agent list` with the named sessions' status and `state_change_seq` replaced."""
    data = json.loads(captured("agent_list.json"))
    for agent in data["result"]["agents"]:
        got = states.get(agent["agent_session"]["value"])
        if got is not None:
            agent["agent_status"], agent["state_change_seq"] = got
    return Outcome(0, json.dumps(data), "")


class RealBridge(Bridge):
    """Lists sessions by asking the real bridge program, which asks a `herdr` that answers with `listing_with`."""

    def __init__(self, program: BridgeProgram, herdr: FakeHerdr) -> None:
        self.program, self.herdr = program, herdr
        self.down = False
        self.asked = 0
        self.hold: asyncio.Event | None = None
        """When an event, each listing is taken and then answered only once the event is set, so a check can be kept in
        flight while the test changes the world."""

    def state(self, status: str, seq: int, session: str = SESSION) -> None:
        self.herdr.replies[("agent", "list")] = listing_with({session: (status, seq)})

    async def sessions(self, access: Access) -> SessionList:
        self.asked += 1
        if self.down:
            raise BridgeFailed("herdr_unavailable")
        got = self.program.get("/v1/sessions")
        assert got.status == 200
        if self.hold is not None:
            await self.hold.wait()
        return wire.sessions(json.dumps(got.body).encode())

    async def whoami(self, access: Access) -> Whoami:
        raise AssertionError("not used")

    async def read(self, access: Access, session_id: str, lines: int) -> Screen:
        return Screen("the end of the screen", False, 1)

    async def prompt(self, access: Access, session_id: str, text: str) -> None:
        raise AssertionError("not used")

    async def start(self, access: Access, directory: str, label: str, model: str | None) -> Session:
        raise AssertionError("not used")

    async def close(self, access: Access, session_id: str) -> None:
        raise AssertionError("not used")

    async def upload(self, access: Access, session_id: str, name: str, data: bytes) -> None:
        raise AssertionError("not used")

    async def outputs(self, access: Access, session_id: str) -> tuple[OutFile, ...]:
        raise AssertionError("not used")

    async def download(self, access: Access, session_id: str, name: str, max_bytes: int) -> bytes:
        raise AssertionError("not used")


@dataclass
class MemoryWatches(Watches):
    """The armed watches in a list, for tests that have no database: `arm` records the request."""

    armed: list[Arm] = field(default_factory=list[Arm])

    async def arm(self, arm: Arm) -> Armed:
        self.armed.append(arm)
        return Armed(len(self.armed), True)

    async def disarm(self, household_id: int, person_id: int, kind: str, target: str) -> bool:
        raise AssertionError("not used")

    async def live(self, household_id: int, person_id: int) -> tuple[Watch, ...]:
        raise AssertionError("not used")

    async def get(self, watch_id: int) -> Watch | None:
        raise AssertionError("not used")

    async def due(self, limit: int) -> tuple[Watch, ...]:
        raise AssertionError("not used")

    async def record(self, watch_id: int, version: int, check: Check) -> bool:
        raise AssertionError("not used")

    async def expire(self, keep_s: float) -> Counts:
        raise AssertionError("not used")


class DownWatches(MemoryWatches):
    """A store that cannot be written."""

    async def arm(self, arm: Arm) -> Armed:
        raise WatchesUnavailable("down")


@dataclass
class Watching:
    home: World
    bridge: RealBridge
    subscriptions: FakeSubscriptions
    connections: HeldConnections
    db: Database
    db_url: str

    @property
    def person(self) -> int:
        return self.home.elodie

    async def arm(self, status: Status = "idle", seq: int = 1000, bench: int | None = None, target: str = SESSION,
                  armed_by: ArmedBy = "handoff", tools: tuple[str, ...] | None = None) -> int:
        """Watch the session as a hand-off from the state it is in; the watch's id."""
        kind = CONFIG.kinds[NAME]
        arm = Arm(self.home.home, self.person, NAME, target, "bridge-capture", bench, armed_by, kind.track, kind.when,
                  kind.handoff_until, tools, kind.interval_s, datetime.now(UTC) + timedelta(hours=kind.handoff_hours),
                  items_of(target, Session(target, "bridge-capture", "dir", status, seq, None)))
        return (await services.get(Watches).arm(arm)).id

    async def tick(self) -> Counter[str]:
        """One tick of the watches job, after making every watch due."""
        await self.due_now()
        return await job.tick()

    async def due_now(self) -> None:
        async with self.db.connection() as conn:
            await conn.execute("UPDATE watches SET next_check_at = now() - interval '1 second'")

    async def settle(self) -> None:
        """Every wake so far has been told, so the watches are checked again."""
        async with self.db.connection() as conn:
            await conn.execute("UPDATE wakes SET settled_at = now(), outcome = 'turn' WHERE settled_at IS NULL")

    def subscribe(self) -> None:
        self.subscriptions.rows.append(Subscription(1, self.home.home, self.person, browser(1)))


@asynccontextmanager
async def watching(url: str, after: Watching | None = None) -> AsyncGenerator[Watching]:
    """A fresh process over `url`. With `after`, it serves the household and person of that earlier process, as a pod of
    the other site does after the lease moves: nothing in memory, the same rows in the database."""
    with tempfile.TemporaryDirectory() as directory:
        async with bench_world(url) as w:
            if after is not None:
                w.home, w.elodie = after.home.home, after.home.elodie
            herdr = FakeHerdr({("agent", "list"): listing_with({}), ("tab", "list"): Outcome(0, captured("tab_list.json"), "")})
            bridge = RealBridge(BridgeProgram(Path(directory), herdr), herdr)
            db = PoolDatabase(url, connect_timeout_s=5.0)
            await db.open()
            subs, connections = FakeSubscriptions(), HeldConnections()
            connections.connect(w.home, f"https://127.0.0.1:7843#sha256={PIN}", "token", "herdr", w.elodie)
            wired = ((Bridge, bridge), (Watches, PostgresWatches(db)), (Wakes, PostgresWakes(db)), (Screens, PostgresScreens(db)),
                     (Subscriptions, subs), (Connections, connections))
            for interface, impl in wired:
                services.register(interface, impl)
            try:
                yield Watching(w, bridge, subs, connections, db, url)
            finally:
                for interface, _ in wired:
                    services.unregister(interface)
                await db.close()


def told(url: str) -> list[tuple[str, str | None]]:
    """The wakes stored so far as (event id, the status the first item changed to)."""
    got = scalar(url, "SELECT coalesce(json_agg(json_build_array(event_id, changes->'items'->0->'after'->>'status') "
                      "ORDER BY id), '[]') FROM wakes WHERE kind = 'watch'")
    return [(e, s) for e, s in got]


def checked(url: str) -> bool:
    """Every live watch has had a check recorded since it was armed or last made due: none is due now."""
    return bool(scalar(url, "SELECT coalesce(bool_and(next_check_at > now()), false) FROM watches WHERE state <> 'ended'"))


def states(url: str) -> list[tuple[str, int]]:
    got = scalar(url, "SELECT coalesce(json_agg(json_build_array(b.value->>'status', (b.value->>'seq')::int)), '[]') "
                      "FROM watches w, jsonb_each(w.baseline) b WHERE w.state <> 'ended'")
    return [(s, n) for s, n in got]
