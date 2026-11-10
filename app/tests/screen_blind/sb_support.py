"""Shared setup of the blind screen-layout suite (`~/scratch/ashley/kiosk-layout/spec.txt`, sections 9 and 10): the real
Postgres Workshop on a throwaway database with a recording Live, one household with a tablet, and readers of a screen
bench's log (no person-scoped read may see it, so the suite reads the tables). Every name the spec leaves open is
made here, so a reconciler rewires one file: see `gaps.txt`."""

import json
import re
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any

import psycopg
from ashley import services
from ashley.db.database import Database
from ashley.db.pool import PoolDatabase
from ashley.live.events import ScreenChanged
from ashley.live.live import Live
from ashley.workshop import rules as workshop_rules
from ashley.workshop.codec import decode_command
from ashley.workshop.commands import Add, Command, Move, ScreenCommand
from ashley.workshop.decide import Accepted, replay
from ashley.workshop.model import HER, By, Owner, Piece, Place, Size, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules, load_screen
from ashley.workshop.screen_controls import Control, decode, encode
from ashley.workshop.workshop import Applied, ScreenView, Workshop
from contract.conversations_support import household, person, scalar
from live_support import FakeLive

CLOCK, HOME, CONTROLS, CONVERSATION = 1, 2, 3, 4
"""The seed's piece ids (`screen_seed.json`: clock, home, controls, conversation, each Add of seqs 1 to 4)."""
SEEDED = 4
HALL = Control("hall-light", "Hall light", "light.turn_on", "light.zq_hall")
PORCH = Control("porch-off", "Porch off", "light.turn_off", "light.zq_porch")
NIGHT = Control("night", "Night", "scene.turn_on", "scene.zq_night")


@dataclass(frozen=True)
class World:
    """Alana and Sam share household `home`, with a tablet and a kitchen screen (form `other`), a satellite and a revoked
    device; Zed is alone in `next_door` with `theirs`."""

    url: str
    home: int
    next_door: int
    alana: Owner
    sam: Owner
    zed: Owner
    tablet: int
    kitchen: int
    satellite: int
    revoked: int
    theirs: int


@dataclass(frozen=True)
class Env:
    world: World
    workshop: Workshop
    live: FakeLive
    database: Database


def add_device(url: str, household_id: int, name: str = "tablet", place: str = "hallway", form: str = "other",
               revoked: bool = False) -> int:
    """A device row of `form` (`other`, `satellite`, `house`), revoked or not."""
    extra = {"other": "", "satellite": ", esphome_host", "house": ", house"}[form]
    values = {"other": "", "satellite": ", 'sat.test'", "house": ", true"}[form]
    made = int(scalar(url, "INSERT INTO devices (household_id, name, place, audience, medium, kind, token_sha256" + extra
                      + ") VALUES (%s, %s, %s, 'present', 'text', 'chat', sha256(gen_random_uuid()::text::bytea)" + values
                      + ") RETURNING id", (household_id, name, place)))
    if revoked:
        scalar(url, "UPDATE devices SET revoked_at = now() WHERE id = %s RETURNING id", (made,))
    return made


def world_on(url: str) -> World:
    home, away = household(url, "home"), household(url, "next door")
    return World(url, home, away, Owner(home, person(url, home, "Alana")), Owner(home, person(url, home, "Sam")),
                 Owner(away, person(url, away, "Zed")), add_device(url, home), add_device(url, home, "kitchen", "kitchen"),
                 add_device(url, home, "sat", "den", "satellite"), add_device(url, home, "old", "attic", revoked=True),
                 add_device(url, away))


def build_workshop(database: Database, screen: Rules | None = None) -> Workshop:
    """The Postgres Workshop; `screen` the screen rules it decides by when a test builds its own. The spec fixes no name
    for that constructor argument: this is the one place that guesses it."""
    bench = workshop_rules.load()
    if screen is None:
        return PostgresWorkshop(database, bench)
    named: dict[str, Rules] = {"screen_rules": screen}
    return PostgresWorkshop(database, bench, **named)


@asynccontextmanager
async def env(url: str, screen: Rules | None = None) -> AsyncGenerator[Env]:
    database = PoolDatabase(url)
    await database.open()
    live = FakeLive()
    workshop = build_workshop(database, screen)
    services.register(Live, live)
    services.register(Workshop, workshop)
    try:
        yield Env(world_on(url), workshop, live, database)
    finally:
        for interface in (Live, Workshop):
            services.unregister(interface)
        await database.close()


def add(owner: Owner | None, kind: str, title: str = "t", body: str = "", size: Size = "small") -> Add:
    return Add(HER if owner is None else By(owner.person_id), kind, Text(title, body), size)


def mv(owner: Owner | None, piece_id: int, order: int, size: Size = "small") -> Move:
    return Move(HER if owner is None else By(owner.person_id), piece_id, Place(order, size))


def put_rows(url: str, device_id: int, household_id: int, *controls: Control) -> None:
    """The device's `device_controls` rows, as they are before its screen bench exists."""
    with psycopg.connect(url, autocommit=True) as conn:
        for n, c in enumerate(controls):
            conn.execute("INSERT INTO device_controls (device_id, household_id, name, position, label, action, "
                         "entity_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                         (device_id, household_id, c.id, n, c.label, c.action, c.entity_id))


def rows_of(url: str, device_id: int) -> int:
    return int(scalar(url, "SELECT count(*) FROM device_controls WHERE device_id = %s", (device_id,)))


def benches_of(url: str, device_id: int) -> list[int]:
    with psycopg.connect(url) as conn:
        return [int(r[0]) for r in conn.execute("SELECT id FROM benches WHERE device_id = %s", (device_id,))]


def log_of(url: str, device_id: int) -> list[tuple[int, Command, str]]:
    """The screen bench's command log, in seq order, as (seq, command, outcome); read from the tables."""
    with psycopg.connect(url) as conn:
        found = conn.execute("SELECT c.seq, c.person_id, c.command, c.outcome FROM bench_commands c "
                             "JOIN benches b ON b.id = c.bench_id WHERE b.device_id = %s ORDER BY c.seq",
                             (device_id,)).fetchall()
    return [(int(seq), decode_command(command, By(who)), str(outcome)) for seq, who, command, outcome in found]


def replayed(url: str, device_id: int, rules: Rules | None = None) -> tuple[tuple[Piece, ...], list[str]]:
    """The log replayed from empty through `decide` under the screen rules: the pieces it ends with and each row's
    outcome."""
    rows = log_of(url, device_id)
    decisions = replay([command for _, command, _ in rows], rules or load_screen())
    pieces: tuple[Piece, ...] = ()
    outcomes: list[str] = []
    for d in decisions:
        pieces = d.state.pieces
        outcomes.append("accepted" if isinstance(d, Accepted) else d.reason)
    return pieces, outcomes


def changed(live: FakeLive) -> list[ScreenChanged]:
    return [e for e in live.published if isinstance(e, ScreenChanged)]


def piece_of(view: ScreenView, kind: str) -> Piece:
    return next(p for p in view.pieces if p.kind == kind)


def buttons_of(view: ScreenView) -> tuple[Control, ...]:
    return decode(piece_of(view, "controls").text.body)


def body_of(*controls: Control) -> str:
    return encode(controls)


def wide_rules(kinds: int, max_pieces: int) -> Rules:
    """Screen rules over `kinds` extra one-each kinds `k1`..., so a screen can be filled to `max_pieces`."""
    base = load_screen()
    extra = {f"k{i}": Kind(f"k{i}", "screen", f"K{i}", 1, "screen") for i in range(1, kinds + 1)}
    return replace(base, kinds={**base.kinds, **extra}, max_pieces=max_pieces, required=frozenset(), one_each=True)


async def run_all(workshop: Workshop, world: World, device_id: int, *commands: ScreenCommand) -> list[Applied]:
    return [await workshop.apply_screen(world.home, device_id, c) for c in commands]


def json_of(body: str) -> Any:
    return json.loads(body)


def fields_of(lines: list[str]) -> list[Mapping[str, str]]:
    """Each logfmt line as its key=value pairs."""
    pair = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S*)')
    return [{k: v.strip('"') for k, v in pair.findall(line)} for line in lines]


def adds(rows: list[tuple[int, Command, str]]) -> list[Add]:
    """The Adds among logged commands, asserting each row is one."""
    found = [c for _, c, _ in rows if isinstance(c, Add)]
    assert len(found) == len(rows), "a row of the log is not an Add"
    return found
