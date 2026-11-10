"""A bench captured as data, served by a Workshop that only reads it: what the bench-act eval (`evals.bench_act`) stands
her real bench tools on. It sits here because only `tools` may reach the workshop's types."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import services
from ..workshop.model import Bench, Owner, Piece, Place, Text
from ..workshop.workshop import BenchView, NullWorkshop, Workshop

AT = datetime(2026, 11, 8, tzinfo=UTC)
OUTSIDE_KINDS = ("file", "image", "site", "video", "reader", "recipe", "clip", "audio")


@dataclass(frozen=True)
class Capture:
    bench: Bench
    pieces: tuple[Piece, ...]
    run_result: str

    def household_only(self) -> "Capture":
        """The same bench without its outside-kind pieces."""
        return Capture(self.bench, tuple(p for p in self.pieces if p.kind not in OUTSIDE_KINDS), self.run_result)


def load(path: Path) -> Capture:
    """The capture in the JSON file `path`: a bench, its pieces and the result a run of its model returns."""
    raw: dict[str, Any] = json.loads(path.read_text())
    b = raw["bench"]
    pieces = tuple(Piece(p["id"], p["kind"], Text(p["title"], p["body"]), p["version"], Place(i, "medium"), p["id"])
                   for i, p in enumerate(raw["pieces"]))
    return Capture(Bench(b["id"], b["household_id"], b["owner_id"], b["title"], AT, None, len(pieces), AT, "3d"),
                   pieces, json.dumps(raw["run_result"]))


class CapturedWorkshop(NullWorkshop):
    """Reads the captured bench; nothing else is served."""

    def __init__(self, capture: Capture) -> None:
        self._capture = capture

    async def read(self, owner: Owner, bench_id: int) -> BenchView:
        return BenchView(self._capture.bench, self._capture.pieces, ())

    async def open_benches(self, owner: Owner) -> list[Bench]:
        return [self._capture.bench]


def install(capture: Capture) -> None:
    """Make the captured bench the process's Workshop."""
    services.register(Workshop, CapturedWorkshop(capture))


def uninstall() -> None:
    services.unregister(Workshop)
