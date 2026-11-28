"""Her tool to move the view of a bench (`channels.turn_tools`): `bench_show` brings pieces, or the whole bench, into view
on the owner's screens, or puts them away. It publishes `ashley.live.events.BenchShown` and changes nothing: no command,
no stored view, and a screen that opens later is not told."""

import time
from collections.abc import Mapping

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..live.events import BenchShown, Shown
from ..live.live import Live
from ..workshop.json_shape import list_of
from ..workshop.model import Owner
from ..workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from . import bench_results
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools

NAME = "bench_show"
INSTRUCTIONS = ("When the person asks to see, show, put away or zoom to pieces of the bench, move their view with "
                "bench_show: the pieces by id, or all of them. It changes nothing on the bench.")
SPEC = ToolSpec(NAME, "Move the person's view of this bench: bring the pieces in `piece_ids` into view in full, or with "
                "`all` the whole bench; with `fold` true put those pieces away as titles instead. It changes nothing on "
                "the bench and cannot be undone; a screen that opens later does not replay it, and where the person has "
                "panned or zoomed since is theirs. Ids not on this bench are ignored.",
                {"type": "object", "properties": {
                    "piece_ids": {"type": "array", "items": {"type": "integer"}},
                    "all": {"type": "boolean", "description": "every piece, in place of piece_ids"},
                    "fold": {"type": "boolean"}}}, outside=False, tier="runs")


class BenchShowTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id

    async def catalogue(self) -> Catalogue:
        return Catalogue((SPEC,), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the record or the model did: each is an error result, logged `tools.call`."""
        started = time.monotonic()
        if call.name != NAME:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, SPEC)
            wanted, fold = _asked(call.arguments)
            on_bench = {p.id for p in (await services.get(Workshop).read(self._owner, self._bench)).pieces}
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except WorkshopUnavailable:
            return bench_results.failed(call, started, "unavailable", "the bench cannot be read right now",
                                        bench=self._bench)
        shown = tuple(i for i in dict.fromkeys(on_bench if wanted is None else wanted) if i in on_bench)
        if not shown:
            return bench_results.failed(call, started, "no_such_piece", "none of those pieces is on the bench's layout; "
                                        "bench_read lists them", bench=self._bench)
        everyone = wanted is None
        services.get(Live).publish(BenchShown(Shown(self._owner.household_id, self._owner.person_id), self._bench,
                                              () if everyone else shown, fold))
        dropped = [] if wanted is None else [i for i in dict.fromkeys(wanted) if i not in on_bench]
        return bench_results.ok(call, started, {"shown": "all" if everyone else list(shown), "fold": fold,
                                                "ignored": dropped}, bench=self._bench, pieces=len(shown), fold=int(fold))


def _asked(args: Mapping[str, object]) -> tuple[list[int] | None, bool]:
    """The piece ids asked for (None for the whole bench) and whether to fold. Raises BadArguments."""
    ids, everyone, fold = args.get("piece_ids"), args.get("all", False), args.get("fold", False)
    if not isinstance(everyone, bool) or not isinstance(fold, bool):
        raise BadArguments("all and fold are true or false")
    if everyone == (ids is not None):
        raise BadArguments("name the pieces in piece_ids, or all, and not both")
    if everyone:
        return None, fold
    items = list_of(ids)
    if items is None or not all(isinstance(i, int) and not isinstance(i, bool) for i in items):
        raise BadArguments("piece_ids is a list of whole numbers")
    return [int(str(i)) for i in items], fold
