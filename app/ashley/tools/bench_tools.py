"""Her tools on one bench, for one turn of its talk (`channels.turn_tools`): read it, and change it through the same
Commands a person's routes build, made by her (`model.HER`) and applied by `Workshop.apply`, so her change is decided,
logged, undoable and announced on Live exactly as a person's is. A refusal comes back to her as a tool error naming the
reason. Built per turn, it remembers which piece versions she has read whole this turn, and refuses an edit of any
other: an edit replaces the whole body, and one made from a cut body would truncate the piece. A stretch of a body
longer than that is changed with `bench_replace`, whose `old` must occur once in the body, on a version she read any
window of."""

import time
from collections.abc import Iterable

from .. import services
from ..people.units import metric_of
from ..people.zone import zone_of
from ..inference.model import ToolCall, ToolResult
from ..workshop import rules as workshop_rules
from ..workshop import reader as workshop_reader
from ..workshop.bench_file import needs_bytes
from ..workshop.commands import Add, Command, Edit, Point, type_of
from ..workshop.model import HER, Owner, Piece, Text
from ..workshop.rules import Rules
from ..workshop.workshop import Applied, BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from ..files import config as files_config
from ..tidy import config as tidy_config
from ..tidy.offer import to_check
from ..tidy.tidy import Tidy
from ..files.store import StoreUnavailable
from . import bench_config, bench_file_text, bench_lead, bench_now, bench_page, bench_results, bench_view
from .tainted import her
from .bench_args import (COMMAND_TOOLS, BadArguments, check_names, command_of, offset_of, piece_id_of,
                         quote_of, replacement_of)
from .bench_citations import Citations, PeopleTurns
from .bench_config import BenchToolsConfig
from .bench_reference import References, Refused, Said
from .bench_specs import INSTRUCTIONS, specs
from . import look_up_config
from .results import Results
from .tools import Catalogue, Tools

RULES = workshop_rules.load()
CONFIG = bench_config.load()
LOOK_UP = look_up_config.load()
TIDY = tidy_config.load()
_READS = ("bench_read", "bench_read_piece", "bench_shelf")
_OWN = _READS + ("bench_replace", "bench_point")


class BenchTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int, rules: Rules = RULES,
                 config: BenchToolsConfig = CONFIG, lead: bool = False, results: Results | None = None,
                 said: Said | None = None, turns: PeopleTurns | None = None) -> None:
        self._lead = lead
        self._added = 0   # pieces she added this turn, counted only on a fresh arrival
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._numbered = results or Results()
        self._references = References(self._owner, bench_id, rules, self._numbered, said)
        self._citations = Citations(self._owner, bench_id, rules, turns)
        self._rules = rules
        self._config = config
        self._whole: set[tuple[int, int]] = set()   # (piece id, version) she has read or written whole this turn
        self._seen: set[tuple[int, int]] = set()    # the same, or read in any window
        self._viewed = False                        # `now` is read once per turn, when first asked for
        self._now: str | None = None

    async def catalogue(self) -> Catalogue:
        """The tools, their instructions and `now`, the bench as it stood when the turn began (`bench_now`): read once
        per turn, None when the bench cannot be read."""
        text = f"{INSTRUCTIONS}\n\n{bench_lead.lead(self._config.lead_adds)}" if self._lead else INSTRUCTIONS
        return Catalogue(specs(self._rules), text, now=await self._view_now())

    async def _view_now(self) -> str | None:
        if not self._viewed:
            self._viewed = True
            try:
                view = await services.get(Workshop).read(self._owner, self._bench)
                self._now = bench_now.now(view, self._rules, self._config.read_body_chars)
            except (BenchNotFound, WorkshopUnavailable):
                self._now = None
        return self._now

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench or the model did: each is an error result, logged `tools.call`. An argument
        the tool does not define is `bad_arguments`, and nothing is read or applied; a ValueError from the Workshop
        (text it cannot store) is `bad_text`."""
        started = time.monotonic()
        if call.name not in _OWN + COMMAND_TOOLS:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, next(s for s in specs(self._rules) if s.name == call.name))
            if call.name == "bench_read":
                return await self._read(call, started)
            if call.name == "bench_read_piece":
                return await self._read_piece(call, started)
            if call.name == "bench_shelf":
                return await self._shelf(call, started)
            if call.name == "bench_replace":
                return await self._replace(call, started)
            if call.name == "bench_point":
                return await self._point(call, started)
            return await self._command(call, started)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except Refused as e:
            return bench_results.failed(call, started, e.outcome, e.reason, bench=self._bench)
        except ValueError:
            return bench_results.failed(call, started, "bad_text", bench_results.BAD_TEXT_HINT, bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and takes no change",
                                        bench=self._bench)
        except (WorkshopUnavailable, StoreUnavailable):
            return bench_results.failed(call, started, "unavailable", "the bench cannot be reached right now",
                                        bench=self._bench)

    async def _read(self, call: ToolCall, started: float) -> ToolResult:
        view = await services.get(Workshop).read(self._owner, self._bench)
        limit = self._config.read_body_chars
        self._saw(view.pieces, limit)
        zone = await zone_of(self._owner.household_id)
        body = bench_view.overview(view, self._rules, limit, self._config.recent_commands, zone,
                                  await metric_of(self._owner.household_id))
        checks = await to_check(services.get(Tidy), self._bench, view.pieces, TIDY)
        body = {**body, "to_check": checks} if checks else body
        shows = self._rules.shows_outside(p.kind for p in view.pieces) or any(p.outside for p in view.pieces)
        return bench_results.ok(call, started, body, outside=shows, bench=self._bench, pieces=len(view.pieces))

    async def _shelf(self, call: ToolCall, started: float) -> ToolResult:
        view = await services.get(Workshop).read(self._owner, self._bench)
        return bench_results.ok(call, started, bench_view.shelf(view), outside=self._rules.shows_outside(
            p.kind for p in view.shelf) or any(p.outside for p in view.shelf), bench=self._bench, pieces=len(view.shelf))

    async def _read_piece(self, call: ToolCall, started: float) -> ToolResult:
        piece_id = piece_id_of(call.arguments)
        offset = offset_of(call.arguments)
        view = await services.get(Workshop).read(self._owner, self._bench)
        found = [p for p in view.pieces if p.id == piece_id]
        if not found:
            return bench_results.failed(call, started, "no_such_piece", bench_results.HINTS["no_such_piece"],
                                        bench=self._bench, piece=piece_id)
        self._saw(found, self._config.piece_chars, offset)
        text = await bench_file_text.text_of(self._owner.household_id, found[0], files_config.load())
        shown = bench_view.piece(
            found[0], self._rules, self._config.piece_chars, offset,
            bench_view.changed_at(view, found[0], await zone_of(self._owner.household_id)), text,
            await metric_of(self._owner.household_id))
        if bench_page.address_of(found[0], self._rules) is not None:
            shown = {**shown, **bench_view.page_of(await bench_page.page_text(
                found[0], self._rules, self._numbered, LOOK_UP, self._config.piece_chars))}
        return bench_results.ok(call, started, shown, outside=self._rules.shows_outside([found[0].kind]) or found[0].outside,
                                bench=self._bench, piece=piece_id)

    async def _replace(self, call: ToolCall, started: float) -> ToolResult:
        want = replacement_of(call.arguments)
        if (want.piece_id, want.base_version) not in self._seen:
            return bench_results.failed(
                call, started, "unread", f"read piece {want.piece_id} with bench_read_piece, then replace from the "
                "version it gives", bench=self._bench, command="edit", piece=want.piece_id)
        view = await services.get(Workshop).read(self._owner, self._bench)
        current = next((p for p in view.pieces if p.id == want.piece_id), None)
        if current is None:
            return bench_results.failed(call, started, "no_such_piece", bench_results.HINTS["no_such_piece"],
                                        bench=self._bench, command="edit", piece=want.piece_id)
        if current.version != want.base_version:
            return bench_results.failed(call, started, "stale_base", bench_results.HINTS["stale_base"],
                                        bench=self._bench, command="edit", piece=want.piece_id)
        if self._references.shows_page(current.kind):
            raise BadArguments("a site, video, reader or recipe piece is changed with bench_edit, by result (a site or video also by a URL the person gave, a recipe also by serves alone)")
        first = current.text.body.find(want.old)
        if first < 0:
            raise BadArguments("old does not occur in the piece; read the window again and copy it exactly")
        if current.text.body.find(want.old, first + 1) >= 0:
            raise BadArguments("old occurs more than once in the piece; give more of the text around it")
        body = current.text.body.replace(want.old, want.new, 1)
        edit = Edit(her(), want.piece_id, want.base_version, Text(current.text.title, body))
        await self._citations.check(edit)
        return await self._apply(call, started, edit, whole=False)

    async def _point(self, call: ToolCall, started: float) -> ToolResult:
        piece_id, quote = piece_id_of(call.arguments), quote_of(call.arguments)
        view = await services.get(Workshop).read(self._owner, self._bench)
        current = next((p for p in view.pieces if p.id == piece_id), None)
        if current is None:
            return bench_results.failed(call, started, "no_such_piece", bench_results.HINTS["no_such_piece"],
                                        bench=self._bench, command="point", piece=piece_id)
        passage = None
        kind = self._rules.kinds.get(current.kind)
        if quote and kind is not None and kind.format == "reader":
            page = workshop_reader.page_of(current.text.body)
            passage = None if page is None else workshop_reader.locate(page, quote)
            if passage is None:
                raise BadArguments("quote must occur exactly once in the page's text, inside one paragraph: copy it "
                                   "exactly from bench_read_piece, with more words around it if it repeats")
        return await self._apply(call, started, Point(HER, piece_id, current.version, passage), whole=False)

    async def _command(self, call: ToolCall, started: float) -> ToolResult:
        command = command_of(call.name, await self._references.resolve(call.name, call.arguments))
        kind = type_of(command)
        if isinstance(command, Add) and needs_bytes(self._rules, command.kind):
            return bench_results.failed(call, started, "bad_file", bench_results.HINTS["bad_file"], bench=self._bench,
                                        command=kind)
        if isinstance(command, Edit) and (command.piece_id, command.base_version) not in self._whole:
            return bench_results.failed(
                call, started, "unread", f"read piece {command.piece_id} whole with bench_read_piece, then edit "
                "from the version it gives", bench=self._bench, command=kind, piece=command.piece_id)
        if isinstance(command, Add) and self._lead and self._added >= self._config.lead_adds:
            return bench_results.failed(
                call, started, "ask_first", f"a bench just opened takes {self._config.lead_adds} pieces in its first "
                "turn and this one has them: say what else you would add and ask the person", bench=self._bench,
                command=kind)
        if isinstance(command, (Add, Edit)):
            await self._citations.check(command)
        return await self._apply(call, started, command)

    async def _apply(self, call: ToolCall, started: float, command: Command, whole: bool = True) -> ToolResult:
        """Apply `command`; `whole` is whether what it wrote was a whole body she composed, to edit again as such."""
        kind = type_of(command)
        applied = await services.get(Workshop).apply(self._owner, self._bench, command)
        if applied.outcome != "accepted":
            return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome],
                                        bench=self._bench, command=kind, seq=applied.seq)
        return bench_results.ok(call, started, self._wrote(command, applied, whole), bench=self._bench, command=kind,
                                seq=applied.seq, piece=applied.piece_id)

    def _wrote(self, command: Command, applied: Applied, whole: bool) -> dict[str, object]:
        """What her accepted command left, for the model; what she wrote herself she has seen whole."""
        body: dict[str, object] = {"seq": applied.seq, "piece_id": applied.piece_id}
        if isinstance(command, Add) and applied.piece_id is not None:
            self._added += 1
            self._know(applied.piece_id, 1, whole)
            body["version"] = 1
        if isinstance(command, Edit):
            self._know(command.piece_id, command.base_version + 1,
                       whole or len(command.text.body) <= self._config.piece_chars)
            body["version"] = command.base_version + 1
        return body

    def _know(self, piece_id: int, version: int, whole: bool) -> None:
        """She knows the piece's content at `version`; `whole` when she can edit it by a whole body."""
        self._seen.add((piece_id, version))
        if whole:
            self._whole.add((piece_id, version))

    def _saw(self, pieces: Iterable[Piece], limit: int, offset: int | None = None) -> None:
        """Pieces as `bench_read` (offset None) or a window of `bench_read_piece` at `offset` showed them."""
        for p in pieces:
            fits = len(p.text.body) <= limit and not offset
            if fits:
                self._whole.add((p.id, p.version))
            if fits or offset is not None:
                self._seen.add((p.id, p.version))
