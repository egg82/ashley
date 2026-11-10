"""Shared pieces of the cue's blind contract tests: rules with a video kind, a site kind and a note kind, builders for a
video piece and a cue, and a fold of `decide` over commands that does not lean on `replay`, and a real Postgres workshop with a recording Live."""

from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType

from ashley import services
from ashley.db.pool import PoolDatabase
from ashley.live.events import BenchChanged, BenchCued
from ashley.live.live import Live
from ashley.workshop.commands import Add, Command, Cue, CueAction, Undo
from ashley.workshop.decide import EMPTY, Accepted, BenchState, Decision, Refused, decide
from ashley.workshop.embed import MAX_START
from ashley.workshop.model import By, Owner, Text
from ashley.workshop.postgres import PostgresWorkshop
from ashley.workshop.rules import Kind, Rules
from ashley.workshop.workshop import Workshop
from contract.conversations_support import household, person
from live_support import FakeLive

NOTE = Kind("note", "stored", "Note", 100)
SITE = Kind("site", "live", "Site", 500, "site")
VIDEO = Kind("video", "live", "Video", 2200, "video")
RULES = Rules(MappingProxyType({"note": NOTE, "site": SITE, "video": VIDEO}), max_pieces=6, title_max_chars=20,
              recent_commands=10, undo_window=100)
WITHOUT_VIDEO = Rules(MappingProxyType({"note": NOTE, "site": SITE}), max_pieces=6, title_max_chars=20,
                      recent_commands=10, undo_window=100)
HER = By(None)
ALANA = By(7)
TUBE = '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
SITE_URL = "https://example.com/page"
BOUNDS: tuple[float, ...] = (0, 0.0, 0.5, 1, 90.25, MAX_START - 1, MAX_START)


def add_video(by: By = HER) -> Add:
    return Add(by, "video", Text("v", TUBE), "medium")


def add_note(by: By = ALANA) -> Add:
    return Add(by, "note", Text("n", "x"), "small")


def add_site(by: By = ALANA) -> Add:
    return Add(by, "site", Text("s", SITE_URL), "small")


def cue(piece_id: int, action: CueAction, seconds: float | None = None, by: By = HER) -> Cue:
    return Cue(by, piece_id, action, seconds)


def fold(commands: Iterable[Command], rules: Rules = RULES, state: BenchState = EMPTY) -> list[Decision]:
    out: list[Decision] = []
    for command in commands:
        decision = decide(state, command, rules)
        out.append(decision)
        state = decision.state
    return out


def last(*commands: Command, rules: Rules = RULES) -> Decision:
    return fold(commands, rules)[-1]


def reason(decision: Decision) -> str:
    assert isinstance(decision, Refused), f"expected a refusal, got {decision}"
    return decision.reason


def accepted(decision: Decision) -> Accepted:
    assert isinstance(decision, Accepted), f"expected an acceptance, got {decision}"
    return decision


def undo(seq: int, by: By = ALANA) -> Undo:
    return Undo(by, seq)




@dataclass(frozen=True)
class World:
    """Alana and Sam share household 1; Zed is alone in household 2."""

    alana: Owner
    sam: Owner
    zed: Owner


def world(url: str) -> World:
    h1, h2 = household(url, "one"), household(url, "two")
    return World(Owner(h1, person(url, h1, "Alana")), Owner(h1, person(url, h1, "Sam")), Owner(h2, person(url, h2, "Zed")))


@asynccontextmanager
async def workshop(url: str, live: FakeLive) -> AsyncGenerator[Workshop]:
    db = PoolDatabase(url)
    await db.open()
    services.register(Live, live)
    shop = PostgresWorkshop(db, RULES)
    services.register(Workshop, shop)
    try:
        yield shop
    finally:
        await db.close()


def cued(live: FakeLive) -> list[BenchCued]:
    return [e for e in live.published if isinstance(e, BenchCued)]


def changed(live: FakeLive) -> list[BenchChanged]:
    return [e for e in live.published if isinstance(e, BenchChanged)]
