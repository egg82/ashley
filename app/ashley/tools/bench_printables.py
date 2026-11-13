"""Her tools for a Printables design on a bench, offered on a bench's talk while an object store and Printables are
wired: `printables_files` lists the files of a model a search numbered (`results.Results`), and `bench_add_printables_file`
puts one of them on the bench as a file piece, last. She names a model by its result number and a file by the id
`printables_files` gave, never by a URL: the server finds the model's page from the number and the file's address from
Printables, and the bytes are fetched under the request-forgery boundary (`printables_fetch`) and kept as an upload is
(`workshop.bench_file`), so the Add is hers, visible and undoable.

Outcomes: `unknown_result` (no such number this turn), `not_a_model_page` (the result is not a Printables model),
`no_such_file` (the model has no file with that id), `not_a_model` (the file is not an STL, 3MF or STEP, or its bytes are
not what its name says), `too_large` (over what a bench takes), `needs_login` (Printables would not hand it over without
a login) and `unavailable`. The `tools.call` line carries the outcome, the bench, piece, media type and size; never a
name or a link."""

import time
from collections.abc import Mapping

from .. import services
from ..files.intake import Refused as FileRefused
from ..files.sniff import sniff
from ..files.store import ObjectStore, StoreUnavailable
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..printables.model import Detail, ModelFile
from ..printables.printables import NullPrintables, Printables, PrintablesFailed, model_id_of
from ..workshop import bench_file
from ..workshop import rules as workshop_rules
from ..workshop.model import Owner
from ..workshop.workshop import BenchClosed, BenchNotFound, WorkshopUnavailable
from . import bench_results, results
from .tainted import her
from .bench_args import BadArguments, check_names, result_of
from .tools import Catalogue, Tools

RULES = workshop_rules.load()
FILES, ADD = "printables_files", "bench_add_printables_file"
MODEL_EXTENSIONS = (".stl", ".3mf", ".step", ".stp")
NAME_CHARS = 80
INSTRUCTIONS = ("A model look_up found on Printables is a result number. printables_files lists that model's files (id, "
                "name, size); bench_add_printables_file puts one STL, 3MF or STEP of it on the bench as a file piece, "
                "which a model piece can then start from. Prefer STEP over 3MF over STL when the model offers more than "
                "one, and the file closest to what was asked for.")
HINTS = {
    "unknown_result": "no search result with that number this turn: look it up again, and name a result by the number "
                      "look_up's references give",
    "not_a_model_page": "that result is not a Printables model's page",
    "no_such_file": "that model has no file with that id: printables_files lists them",
    "not_a_model": "only an STL, 3MF or STEP file is taken, and its content must be that kind of file",
    "too_large": "it is larger than a bench takes",
    "needs_login": "Printables does not hand that file to someone who is not logged in; the person can download it "
                   "there and upload it to the bench",
    "unavailable": "Printables or the bench's storage did not answer; nothing was added"}
_FILE_REFUSALS = {"empty": "not_a_model", "type_not_allowed": "not_a_model", "type_mismatch": "not_a_model",
                  "too_large": "too_large"}
_RESULT = {"type": "integer", "description": "The result number look_up's references gave for the model"}
LIST = ToolSpec(FILES, "List the files of a Printables model: each file's id, name and size in bytes, and whether a "
                "bench takes it (an STL, 3MF or STEP no larger than a bench takes).",
                {"type": "object", "properties": {"result": _RESULT}, "required": ["result"]}, reads=True, outside=True)
ADD_SPEC = ToolSpec(ADD, "Put one file of a Printables model on this bench, last, as a file piece. `file` is the id "
                    "printables_files gave.",
                    {"type": "object", "properties": {"result": _RESULT, "file": {"type": "string"}},
                     "required": ["result", "file"]}, outside=False, tier="runs")


class Cannot(Exception):
    """A call that cannot be done, for `outcome`, one of `HINTS`."""

    def __init__(self, outcome: str) -> None:
        super().__init__(outcome)
        self.outcome = outcome


class BenchPrintablesTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int, numbered: results.Results | None = None) -> None:
        self._owner = Owner(household_id, person_id)
        self._bench = bench_id
        self._numbered = numbered

    async def catalogue(self) -> Catalogue:
        """Empty when no object store or no Printables is wired."""
        if not await services.get(ObjectStore).available() or isinstance(services.get(Printables), NullPrintables):
            return Catalogue((), None)
        return Catalogue((LIST, ADD_SPEC), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises for what Printables, the bench or the store did: each is an error result, logged `tools.call`."""
        started = time.monotonic()
        spec = {LIST.name: LIST, ADD_SPEC.name: ADD_SPEC}.get(call.name)
        if spec is None:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            check_names(call.arguments, spec)
            wanted = _file_of(call.arguments) if spec is ADD_SPEC else None
            detail = await self._detail(call.arguments)
            return await (self._list(call, started, detail) if wanted is None
                          else self._add(call, started, detail, wanted))
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e), bench=self._bench)
        except Cannot as e:
            return bench_results.failed(call, started, e.outcome, HINTS[e.outcome], bench=self._bench)
        except FileRefused as e:
            return bench_results.failed(call, started, _FILE_REFUSALS[e.reason], HINTS[_FILE_REFUSALS[e.reason]],
                                        bench=self._bench)
        except PrintablesFailed as e:
            outcome = e.reason if e.reason in ("needs_login", "too_large") else "unavailable"
            return bench_results.failed(call, started, outcome, HINTS[outcome], bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and takes no change",
                                        bench=self._bench)
        except (WorkshopUnavailable, StoreUnavailable):
            return bench_results.failed(call, started, "unavailable", HINTS["unavailable"], bench=self._bench)

    async def _detail(self, args: Mapping[str, object]) -> Detail:
        url = (self._numbered or results.current()).url(result_of(args))
        if url is None:
            raise Cannot("unknown_result")
        model = model_id_of(url)
        if model is None:
            raise Cannot("not_a_model_page")
        return await services.get(Printables).detail(model)

    async def _list(self, call: ToolCall, started: float, detail: Detail) -> ToolResult:
        files = [{"file": f.id, "name": f.name[:NAME_CHARS], "size": f.size, "takes": _takes(f)}
                 for f in detail.model.files]
        return bench_results.ok(call, started, {"files": files}, bench=self._bench, rows=len(files))

    async def _add(self, call: ToolCall, started: float, detail: Detail, wanted: str) -> ToolResult:
        found = next((f for f in detail.model.files if f.id == wanted), None)
        if found is None:
            raise Cannot("no_such_file")
        if not found.name.lower().endswith(MODEL_EXTENSIONS):
            raise Cannot("not_a_model")
        limit = bench_file.CONFIG.max_bytes
        if found.size > limit:
            raise Cannot("too_large")
        data = await services.get(Printables).download(detail.model.id, found.id, limit)
        if not is_model(found.name, data):
            raise Cannot("not_a_model")
        stored, applied = await bench_file.add_file(self._owner, self._bench, her(), data, found.name, "", RULES)
        if applied.outcome != "accepted":
            return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome],
                                        bench=self._bench, command="add", seq=applied.seq)
        return bench_results.ok(call, started, {"seq": applied.seq, "piece_id": applied.piece_id,
                                                 "media_type": stored.media_type, "size": stored.size},
                                bench=self._bench, command="add", seq=applied.seq, piece=applied.piece_id,
                                media_type=stored.media_type, size=stored.size)


def _file_of(args: Mapping[str, object]) -> str:
    wanted = args.get("file")
    if not isinstance(wanted, str) or not wanted.strip():
        raise BadArguments("file is the id printables_files gave, a string")
    return wanted.strip()


def _takes(file: ModelFile) -> bool:
    return file.name.lower().endswith(MODEL_EXTENSIONS) and file.size <= bench_file.CONFIG.max_bytes


def is_model(name: str, data: bytes) -> bool:
    """Whether `data` is the kind of model file `name` says: a binary or ASCII STL, a 3MF with its model part, or a
    STEP with its ISO-10303-21 header."""
    lowered = name.lower()
    if lowered.endswith((".step", ".stp")):
        return data.lstrip().startswith(b"ISO-10303-21")
    media = sniff(data, "", bench_file.CONFIG).media_type
    if lowered.endswith(".3mf"):
        return media == "model/3mf"
    return media == "model/stl" or (media is not None and media.startswith("text/") and data.lstrip()[:5] == b"solid")
