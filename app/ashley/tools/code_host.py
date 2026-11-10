"""Her read of the talking person's own code host (`ashley.codehost`), from the GitLab and GitHub connections that
person made (`ashley.connections`): the projects their token reads, a directory, a file, and a file or a whole
snapshot put on their bench as a file piece. Offered per turn by `ashley.channels.turn_tools.for_turn` where the reply
reaches the speaker alone, and only to a person who connected a host. Reads only: the putting is onto the bench, never
to the host. Arguments and results are never logged; `tools.call` carries the outcome, row and byte counts."""

import mimetypes
import re
import time
from collections.abc import Mapping
from typing import get_args

from .. import services
from ..codehost import addressing
from ..codehost.config import CodeHostConfig
from ..codehost.host import CodeHost, CodeHostFailed
from ..codehost.model import Access, Fetched, Forge, Reason
from ..connections import ports
from ..connections.connections import Connections, ConnectionsUnavailable
from ..files.intake import Refused as FileRefused
from ..files.store import StoreUnavailable
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..workshop import bench_file
from ..workshop import rules as workshop_rules
from ..workshop.model import Owner
from ..workshop.workshop import BenchClosed, BenchNotFound, WorkshopUnavailable
from . import bench_results, file_page
from .tainted import her
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools, ToolsUnavailable

RULES = workshop_rules.load()
PROJECTS, TREE, READ, TO_BENCH = "git_projects", "git_tree", "git_read_file", "bench_add_from_git"
_REF = re.compile(r"^[\w./@+-]{0,200}$")
INSTRUCTIONS = ("The person has connected their own code host, so git_projects lists the repositories their token reads "
                "(the same ones they see there), git_tree lists a directory and git_read_file reads a text file at a "
                "branch, tag or commit (the default branch when none is named). Read the repository itself before "
                "answering a question about how something in it is set up, and say which file you read. You can "
                "only read: nothing you do changes the host.")
BENCH_INSTRUCTIONS = (" bench_add_from_git puts a file, or with no path a whole snapshot as a zip, on this bench as a "
                      "file piece the person can download.")
_HINTS: dict[Reason, str] = {
    "refused": "the host turned the person's token away; they can make a new one and replace it in settings",
    "not_found": "no such project, path or ref, or the person's token cannot read it; git_projects lists what it reads",
    "unreachable": "the code host did not answer in time",
    "too_large": "it is larger than a bench takes",
    "unexpected": "the code host answered with something unexpected"}
_FILE_REFUSALS = {"empty": "there is nothing in it to add", "too_large": "it is larger than a bench takes",
                  "type_not_allowed": "that kind of file is not taken: text, images, PDFs and zip archives are",
                  "type_mismatch": "its content is not the type its name says"}


def _spec(name: str, text: str, properties: dict[str, object], hosts: tuple[Forge, ...], required: list[str],
          reads: bool) -> ToolSpec:
    host = {"type": "string", "enum": list(hosts), "description": "Which connected code host"}
    return ToolSpec(name, text, {"type": "object", "properties": {"host": host, **properties},
                                 "required": (["host"] if len(hosts) > 1 else []) + required}, reads, outside=True, tier="runs")


def specs(hosts: tuple[Forge, ...], on_bench: bool) -> tuple[ToolSpec, ...]:
    project = {"type": "string", "description": "The project's path as git_projects gives it"}
    ref = {"type": "string", "description": "Branch, tag or commit; the default branch when left out"}
    path = {"type": "string", "description": "A path inside the project"}
    found = (
        _spec(PROJECTS, "List the projects the person's token reads, most recently active first.",
              {"search": {"type": "string"}}, hosts, [], True),
        _spec(TREE, "List the files and directories directly under `path` (the project's root when left out).",
              {"project": project, "ref": ref, "path": path}, hosts, ["project"], True),
        _spec(READ, "Read one text file of a project, a page of it at a time: `total_chars` is its length, and while "
              "`next_start` is a number there is more, which a call with `start` set to it reads. Never conclude "
              "something is not in a file before `next_start` is null.",
              {"project": project, "ref": ref, "path": path,
               "start": {"type": "integer", "description": "The character to read from; 0 when left out"}}, hosts,
              ["project", "path"], True))
    if not on_bench:
        return found
    return found + (_spec(TO_BENCH, "Put a file of a project on this bench, last, as a file piece the person can "
                          "download; with no `path`, the whole project at `ref` as a zip.",
                          {"project": project, "ref": ref, "path": path}, hosts, ["project"], False),)


class CodeHostTools(Tools):
    def __init__(self, household_id: int, person_id: int, bench_id: int | None, config: CodeHostConfig,
                 result_chars: int) -> None:
        self._household = household_id
        self._person = person_id
        self._bench = bench_id
        self._config = config
        self._result_chars = result_chars   # a page of a file is fitted under this, so the loop never cuts it
        self._access: dict[Forge, Access] | None = None

    async def catalogue(self) -> Catalogue:
        """Empty when the person has connected no code host. Raises ToolsUnavailable when connections cannot be read."""
        access = await self._connected()
        if not access:
            return Catalogue((), None)
        on_bench = self._bench is not None
        return Catalogue(specs(tuple(access), on_bench), INSTRUCTIONS + (BENCH_INSTRUCTIONS if on_bench else ""))

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, bad arguments, no connection, or the host failing are each an error result."""
        started = time.monotonic()
        names = {PROJECTS, TREE, READ} | ({TO_BENCH} if self._bench is not None else set[str]())
        if call.name not in names:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            access = await self._connected()
        except ToolsUnavailable:
            return bench_results.failed(call, started, "unavailable", "the person's connections cannot be read")
        if not access:
            return bench_results.failed(call, started, "not_connected", "the person has not connected a code host")
        try:
            spec = next(s for s in specs(tuple(access), self._bench is not None) if s.name == call.name)
            check_names(call.arguments, spec)
            return await self._run(call, started, access, call.arguments)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        except CodeHostFailed as e:
            return bench_results.failed(call, started, e.reason, _HINTS[e.reason])
        except FileRefused as e:
            return bench_results.failed(call, started, e.reason, _FILE_REFUSALS[e.reason], bench=self._bench)
        except BenchNotFound:
            return bench_results.failed(call, started, "not_found", "this bench is gone", bench=self._bench)
        except BenchClosed:
            return bench_results.failed(call, started, "closed", "this bench is closed and takes no change",
                                        bench=self._bench)
        except (WorkshopUnavailable, StoreUnavailable):
            return bench_results.failed(call, started, "unavailable", "the bench or its storage cannot be reached "
                                        "right now; nothing was added", bench=self._bench)

    async def _connected(self) -> dict[Forge, Access]:
        if self._access is None:
            found: dict[Forge, Access] = {}
            try:
                held = await ports.opened_all(services.get(Connections), "code_host", self._household, self._person)
            except ConnectionsUnavailable as e:
                raise ToolsUnavailable("connections unavailable") from e
            for forge in get_args(Forge):
                opened = next((o for o in held if o.connection.kind == forge), None)
                if opened is not None:
                    found[forge] = Access(forge, opened.connection.base_url, opened.secret, opened.connection.id)
            self._access = found
        return self._access

    async def _run(self, call: ToolCall, started: float, access: Mapping[Forge, Access],
                   args: Mapping[str, object]) -> ToolResult:
        host = services.get(CodeHost)
        if call.name == PROJECTS:
            return await self._projects(call, started, access, args, host)
        chosen = _chosen(access, args)
        project = _project(chosen, args)
        ref = _ref(args)
        path = _path(args)
        if call.name == TREE:
            page = await host.tree(chosen, project, ref, path)
            return bench_results.ok(call, started, {"entries": [{"path": e.path, "kind": e.kind} for e in page.items],
                                                    "more": page.more}, rows=len(page.items))
        if call.name == READ:
            if not path:
                raise BadArguments("path is a non-empty string")
            return self._read(call, started, await host.file(chosen, project, ref, path, self._config.read_bytes),
                              path, _start(args))
        return await self._to_bench(call, started, host, chosen, project, ref, path)

    async def _projects(self, call: ToolCall, started: float, access: Mapping[Forge, Access],
                        args: Mapping[str, object], host: CodeHost) -> ToolResult:
        search = _text(args, "search", 100, required=False)
        wanted = args.get("host")
        if wanted is not None and wanted not in access:
            raise BadArguments("host is one of: " + ", ".join(access))
        rows: list[dict[str, str | None]] = []
        more = False
        for forge, found in access.items():
            if wanted is not None and wanted != forge:
                continue
            page = await host.projects(found, search)
            more = more or page.more
            rows += [{"host": forge, "path": p.path, "description": p.description[:200], "default_branch": p.default_branch}
                     for p in page.items]
        return bench_results.ok(call, started, {"projects": rows, "more": more}, rows=len(rows))

    def _read(self, call: ToolCall, started: float, got_file: Fetched, path: str, start: int) -> ToolResult:
        try:
            text = got_file.data.decode()
        except UnicodeDecodeError:
            return bench_results.failed(call, started, "binary", "that file is not text; on a bench it can be added "
                                        "as a file piece with bench_add_from_git")
        if start > len(text):
            raise BadArguments(f"start is at most {len(text)}, the file's length in characters")
        body = file_page.page(path, text, start, got_file.more, self._result_chars)
        return bench_results.ok(call, started, body, bytes=len(got_file.data))

    async def _to_bench(self, call: ToolCall, started: float, host: CodeHost, chosen: Access, project: str, ref: str,
                        path: str) -> ToolResult:
        assert self._bench is not None
        if path:
            got = await host.file(chosen, project, ref, path, self._config.snapshot_max_bytes)
            if got.more:
                raise CodeHostFailed("too_large")
            data, name = got.data, path.rsplit("/", 1)[-1]
        else:
            data = await host.archive(chosen, project, ref)
            name = re.sub(r"[^\w.-]+", "-", f"{project}-{ref or 'default'}") + ".zip"
        stored, applied = await bench_file.add_file(Owner(self._household, self._person), self._bench, her(), data, name,
                                                    mimetypes.guess_type(name)[0] or "", RULES)
        if applied.outcome != "accepted":
            return bench_results.failed(call, started, applied.outcome, bench_results.HINTS[applied.outcome],
                                        bench=self._bench, command="add", seq=applied.seq)
        return bench_results.ok(call, started, {"seq": applied.seq, "piece_id": applied.piece_id,
                                                 "media_type": stored.media_type, "size": stored.size},
                                bench=self._bench, command="add", seq=applied.seq, piece=applied.piece_id,
                                media_type=stored.media_type, size=stored.size)


def _chosen(access: Mapping[Forge, Access], args: Mapping[str, object]) -> Access:
    wanted = args.get("host")
    if wanted is None and len(access) == 1:
        return next(iter(access.values()))
    if isinstance(wanted, str) and wanted in ("gitlab", "github") and wanted in access:
        return access[wanted]
    raise BadArguments("host is one of: " + ", ".join(access))


def _text(args: Mapping[str, object], name: str, longest: int, required: bool) -> str:
    value = args.get(name, "")
    if not isinstance(value, str) or "\x00" in value or len(value) > longest or (required and not value.strip()):
        raise BadArguments(f"{name} is a{'' if required else 'n optional'} string of at most {longest} characters")
    return value.strip()


def _project(chosen: Access, args: Mapping[str, object]) -> str:
    value = _text(args, "project", 200, required=True)
    if addressing.reason(chosen.forge, "project", value) is not None:
        raise BadArguments("project is a project's path as git_projects gives it")
    return value


def _path(args: Mapping[str, object]) -> str:
    value = _text(args, "path", 500, required=False).strip("/")
    if addressing.reason("gitlab", "path", value) is not None:
        raise BadArguments("path stays inside the project")
    return value


def _start(args: Mapping[str, object]) -> int:
    value = args.get("start", 0)
    if type(value) is not int or value < 0:
        raise BadArguments("start is a whole number of characters, 0 or more")
    return value


def _ref(args: Mapping[str, object]) -> str:
    value = _text(args, "ref", 200, required=False)
    if not _REF.match(value) or ".." in value:
        raise BadArguments("ref is a branch, tag or commit name")
    return value
