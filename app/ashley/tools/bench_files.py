"""Her tool for a file she makes (`bench_add_file`), offered on a bench's talk while an object store is wired: a file
piece from text she writes, or from what a code piece's latest run gave (its output, or a file it left). It is the
person's upload made by her: the bytes are judged and kept as theirs are, and the Add is hers, so it is as visible and as
undoable. She reads a text file piece with `bench_read_piece`."""

import mimetypes
import time
from collections.abc import Mapping

from .. import services
from ..files.intake import Refused as FileRefused
from ..files.store import ObjectStore, StoreUnavailable
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..runs.runs import Runs, RunsUnavailable
from ..workshop import bench_file
from ..workshop import rules as workshop_rules
from ..workshop.model import Owner
from ..workshop.workshop import BenchClosed, BenchNotFound, WorkshopUnavailable
from . import bench_results
from .tainted import her
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools

RULES = workshop_rules.load()
ADD = "bench_add_file"
INSTRUCTIONS = ("A file the person can download (a CSV, a JSON export, a script's output) is a file piece, made with "
                "bench_add_file from text you write or from what a code piece's latest run gave; its name decides the "
                "type it is offered as. An image or file piece's content is never edited. bench_read_piece reads a text "
                "file's text.")
REFUSALS = {"empty": "there is nothing in it to add", "too_large": "it is larger than a bench takes",
            "type_not_allowed": "that kind of file is not taken: text, images, PDFs and zip archives are",
            "type_mismatch": "its content is not the type its name says"}
SPEC = ToolSpec(ADD, "Add a file piece to this bench, last: either `text` you write, or what the latest run of code "
                "piece `from_piece` gave (its printed output, or the file `file` it left). `name` is the file's name, "
                "with its extension. The person can download it.",
                {"type": "object", "properties": {
                    "name": {"type": "string"}, "text": {"type": "string"}, "from_piece": {"type": "integer"},
                    "file": {"type": "string", "description": "With from_piece: a file the run left, instead of its output"}},
                 "required": ["name"]}, outside=False, tier="runs")


class BenchFileTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id

    async def catalogue(self) -> Catalogue:
        """Empty when no object store is wired."""
        if not await services.get(ObjectStore).available():
            return Catalogue((), None)
        return Catalogue((SPEC,), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what the bench, the store or the model did: each is an error result, logged `tools.call`."""
        started = time.monotonic()
        if call.name != ADD:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, SPEC)
            return await self._add(call, started)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except FileRefused as e:
            return bench_results.failed(call, started, e.reason, REFUSALS[e.reason], bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and takes no change",
                                        bench=self._bench)
        except (WorkshopUnavailable, StoreUnavailable, RunsUnavailable):
            return bench_results.failed(call, started, "unavailable", "the bench or its storage cannot be reached "
                                        "right now; nothing was added", bench=self._bench)

    async def _add(self, call: ToolCall, started: float) -> ToolResult:
        args = call.arguments
        name = args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise BadArguments("name is a non-empty string")
        text = await self._content(args)
        declared = mimetypes.guess_type(name)[0] or ""
        stored, applied = await bench_file.add_file(self._owner, self._bench, her(), text.encode(), name, declared,
                                                    RULES)
        if applied.outcome != "accepted":
            return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome],
                                        bench=self._bench, command="add", seq=applied.seq)
        return bench_results.ok(call, started, {"seq": applied.seq, "piece_id": applied.piece_id,
                                                 "media_type": stored.media_type, "size": stored.size},
                                bench=self._bench, command="add", seq=applied.seq, piece=applied.piece_id,
                                media_type=stored.media_type, size=stored.size)

    async def _content(self, args: Mapping[str, object]) -> str:
        text, source = args.get("text"), args.get("from_piece")
        if (text is None) == (source is None):
            raise BadArguments("give text, or from_piece, and not both")
        if text is not None:
            if not isinstance(text, str):
                raise BadArguments("text is a string")
            return text
        if type(source) is not int:
            raise BadArguments("from_piece is a whole number")
        run = (await services.get(Runs).last_on_bench(self._owner.household_id, self._bench)).get(source)
        if run is None or run.output is None:
            raise BadArguments("that piece has no finished run: run it first (bench_run)")
        wanted = args.get("file")
        if wanted is None:
            return run.output.stdout
        if not isinstance(wanted, str) or wanted not in run.output.files:
            raise BadArguments("file is the name of a file its latest run left: " + ", ".join(sorted(run.output.files)))
        return run.output.files[wanted]
