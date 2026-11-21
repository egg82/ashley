"""A bench's STL or 3MF added to the household's print library, through the Printing service
(`ashley.printing.printing`), as her `printing_upload` tool (`printing_queue_specs`). The bytes are the file piece's, read
from the object store as the bench reads them (`ashley.workshop.model_inputs.importable`, `ashley.files.intake.key_of`).
Offered on a bench's talk where the reply reaches the speaker alone, beside `printing_queue`. A library file starts
nothing, so it is `judged` and not held for the person's OK; queuing it is. Outcomes: `uploaded`, `rejected` (Bambuddy
would not take it), `no_such_piece`, `not_a_model` (not an STL or 3MF file piece), `gone` (the store lacks its bytes),
`refused`, `unreachable`, `unavailable`. Arguments, names and bytes are never logged; `tools.call` carries the bench,
piece, outcome and size."""

import time
from pathlib import PurePosixPath

from .. import services
from ..files.intake import key_of
from ..files.store import ObjectStore, StoreUnavailable
from ..inference.model import ToolCall, ToolResult
from ..printing.model import NotConnected, PrintingFailed, PrintingUnavailable
from ..printing.printing import Printing
from ..workshop import model_inputs
from ..workshop import rules as workshop_rules
from ..workshop.model import Owner
from ..workshop.workshop import BenchNotFound, Workshop, WorkshopUnavailable
from . import bench_results, printing_render
from .printing_queue_specs import MODEL_SUFFIXES, UPLOAD, UPLOAD_INSTRUCTIONS, upload_piece, upload_spec
from .tools import Catalogue, Tools, ToolsUnavailable

RULES = workshop_rules.load()
_REFUSED = ("Bambuddy turned the file away; the household's key may not manage the library, and someone in the household "
            "can replace it in settings with one that may")
_FAILED = {"refused": ("refused", _REFUSED), "unreachable": ("unreachable", "Bambuddy did not answer; nothing was added"),
           "unrecognised": ("not_bambuddy", "Bambuddy answered with something unexpected")}


class PrintUploadTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._connected: bool | None = None

    async def catalogue(self) -> Catalogue:
        """No tools when the household has no printing manager or no object store is wired. Raises ToolsUnavailable when
        the household's link cannot be read."""
        if not await self._is_connected() or not await services.get(ObjectStore).available():
            return Catalogue((), None)
        return Catalogue((upload_spec(),), UPLOAD_INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no manager, a missing piece or Bambuddy failing are each an
        error result."""
        started = time.monotonic()
        if call.name != UPLOAD:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        piece = upload_piece(dict(call.arguments))
        if isinstance(piece, str):
            return bench_results.failed(call, started, "bad_arguments", piece, bench=self._bench)
        try:
            return await self._upload(call, started, piece)
        except (ToolsUnavailable, PrintingUnavailable, WorkshopUnavailable, StoreUnavailable):
            return bench_results.failed(call, started, "unavailable", "the household's connections, the bench or its "
                                        "storage cannot be reached right now; nothing was added", bench=self._bench)
        except NotConnected:
            return bench_results.failed(call, started, "not_connected", "the household has not connected Bambuddy",
                                        bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except PrintingFailed as e:
            outcome, hint = _FAILED[e.reason]
            return bench_results.failed(call, started, outcome, hint, bench=self._bench, piece=piece)

    async def _upload(self, call: ToolCall, started: float, piece_id: int) -> ToolResult:
        if not await self._is_connected():
            raise NotConnected
        shown = await services.get(Workshop).read(self._owner, self._bench)
        piece = next((p for p in shown.pieces if p.id == piece_id), None)
        if piece is None:
            return bench_results.failed(call, started, "no_such_piece", "no piece with that id is on the bench's "
                                        "layout; bench_read lists them", bench=self._bench, piece=piece_id)
        file = model_inputs.importable(piece, RULES)
        if file is None or PurePosixPath(file.name).suffix.lower() not in MODEL_SUFFIXES:
            return bench_results.failed(call, started, "not_a_model", "only an STL or 3MF file piece goes to the print "
                                        "library", bench=self._bench, piece=piece_id)
        data = await services.get(ObjectStore).get(key_of(self._owner.household_id, file.sha256))
        if data is None:
            return bench_results.failed(call, started, "gone", "that file's bytes are no longer in the store",
                                        bench=self._bench, piece=piece_id)
        done = await services.get(Printing).upload(self._owner.household_id, file.name, data)
        return bench_results.ok(call, started, printing_render.uploaded(done), rows=int(done.outcome == "uploaded"),
                                bench=self._bench, piece=piece_id, size=len(data))

    async def _is_connected(self) -> bool:
        if self._connected is None:
            try:
                self._connected = await services.get(Printing).connected(self._owner.household_id)
            except PrintingUnavailable as e:
                raise ToolsUnavailable("printing unavailable") from e
        return self._connected
