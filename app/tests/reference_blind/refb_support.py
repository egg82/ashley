"""Support for the blind reference-by-result tests: her bench tools over a Workshop that judges every command with the
real `decide` (so the kind checks, `bad_site` and `bad_video`, are the shipped ones) and records what it accepted."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from ashley import services
from ashley.channels.said_links import by_people as by_people
from ashley.inference.model import ToolCall, ToolResult
from ashley.tools.bench_reference import Said, SaidUnavailable
from ashley.tools.bench_tools import BenchTools
from ashley.tools.results import Results
from ashley.workshop import rules as workshop_rules
from ashley.workshop.commands import Add, Command, Edit
from ashley.workshop.decide import Accepted, BenchState, decide
from ashley.workshop.model import HER, Owner, Piece, Place, Text
from ashley.workshop.workshop import Applied, Workshop
from bench_tools_support import FakeWorkshop

OWNER = Owner(10, 1)
BENCH = 4
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
WIKI = "https://en.wikipedia.org/wiki/Travelling_salesman_problem"
EDITED = 50
"""The id of the piece an edit is made to."""
OTHER = "https://example.org/other"
"""A URL no source vouches for unless a test says so."""
PASTED = "https://example.org/pasted"


@dataclass
class DecidingShop(FakeWorkshop):
    """`apply` is the real `decide` over the pieces and shelf; an accepted Add or Edit is recorded in `applied`."""

    def __post_init__(self) -> None:
        self.rules = workshop_rules.load()

    async def apply(self, owner: Owner, bench_id: int, command: Command) -> Applied:
        decision = decide(BenchState(self.pieces, 100, shelf=self.shelf), command, self.rules)
        if isinstance(decision, Accepted):
            self.applied.append((owner, bench_id, command))
            return Applied(decision.seq, "accepted", getattr(command, "piece_id", decision.seq))
        return Applied(decision.seq, decision.reason, None)


def piece(pid: int, kind: str, body: str, title: str = "t") -> Piece:
    return Piece(pid, kind, Text(title, body), 1, Place(0, "medium"), pid)


def video_body(url: str, start: int | None = None) -> str:
    return json.dumps({"url": url} if start is None else {"url": url, "start": start})


def said_of(*urls: str) -> Said:
    async def read() -> frozenset[str]:
        return frozenset(urls)
    return read


async def conversation_down() -> frozenset[str]:
    raise SaidUnavailable()


@dataclass
class Rig:
    """Her bench tools for one turn: `results` is the turn's store, `shop` the bench. `put` adds a piece of `kind` (op
    `add`) or edits one already on the bench, read whole first (op `edit`), with the given tool fields."""

    shop: DecidingShop
    tools: BenchTools
    results: Results
    log: list[ToolResult] = field(default_factory=list[ToolResult])

    def call(self, name: str, **args: Any) -> ToolResult:
        got = asyncio.run(self.tools.call(ToolCall(f"c{len(self.log)}", name, args)))
        self.log.append(got)
        return got

    def put(self, op: str, kind: str, **fields: Any) -> ToolResult:
        if op == "add":
            return self.call("bench_add", kind=kind, title="t", **fields)
        assert self.call("bench_read_piece", piece_id=EDITED).is_error is False
        return self.call("bench_edit", piece_id=EDITED, base_version=1, title="t", **fields)

    def command(self) -> Add | Edit:
        """The one Add or Edit the bench accepted."""
        assert len(self.shop.applied) == 1, self.shop.applied
        owner, bench, command = self.shop.applied[0]
        assert (owner, bench, command.by) == (OWNER, BENCH, HER)
        assert isinstance(command, Add | Edit)
        return command


def rig(kind: str = "site", pieces: tuple[Piece, ...] = (), shelf: tuple[Piece, ...] = (), said: Said | None = None,
        results: Results | None = None) -> Rig:
    """A bench holding an edit target of `kind` (its body a URL nothing else uses), and whatever else is given."""
    target = piece(EDITED, kind, "https://example.org/edited" if kind == "site" else video_body("https://example.org/e.mp4"))
    shop = DecidingShop(pieces=(target, *pieces), shelf=shelf)
    services.register(Workshop, shop)
    store = results or Results()
    return Rig(shop, BenchTools(OWNER.household_id, OWNER.person_id, BENCH, results=store, said=said), store)


def error_code(got: ToolResult, *codes: str) -> bool:
    """The call failed and names one of `codes`."""
    return got.is_error and any(c in got.content for c in codes)


def body_of(command: Add | Edit) -> str:
    return command.text.body
