"""A signed-in person's benches (`ashley.workshop.workshop.Workshop`): the piece kinds, open, list (open or closed), read,
close and reopen a bench, and change it by one command at a time (an undo, an archive and a restore included). Only the bench's owner reads or changes it; anyone
else's id is 404 `not_found`, as one that does not exist. A page showing a bench reads it back when `GET /api/live`
says it changed (`LiveBench`). The bench's talk is `api.bench_talk`."""

from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import services
from ..connections.deployment_secrets import DeploymentSecrets
from ..people.units import metric_of
from ..runs import config as runs_config
from ..runs.model import Run
from ..runs.runs import Runs, RunsUnavailable
from ..runs.sandbox import Sandbox
from ..skills.skills import Skills, SkillsUnavailable
from ..workshop import embed, reader
from ..workshop.bench_file import needs_bytes
from ..workshop import rules as workshop_rules
from ..workshop.commands import type_of
from ..workshop.install_piece import carry_out
from ..workshop.installs import InstallRecord, Installs, InstallsUnavailable
from ..workshop.model import SIZES, Bench, Change, Owner, Piece
from ..workshop.provisional import provisional_title
from ..workshop.rules import Kind
from ..workshop.workshop import BenchClosed, BenchNotFound, BenchView, Logged, Workshop, WorkshopUnavailable
from . import bench_opening
from .bench_commands import command_of
from .bench_frames import measure_in_background
from .bench_embed_models import PieceVideo
from .bench_file_models import piece_file
from .bench_reader_models import PiecePointer, PieceReader, PieceRecording
from .bench_recipe import recipe_of
from .bench_site_models import PieceSite, site_of
from .bench_install_models import automation_of
from .bench_run_models import piece_run_of
from .models import ErrorResponse
from .person import Person
from .skill_models import WorkKind
from .workshop_models import (BenchDetail, BenchList, BenchPiece, BenchRequest, BenchSummary, CommandApplied,
                              CommandRefused, AddPieceRequest, CommandRequest, LoggedCommand, PieceKind, PiecePlace, WorkshopKinds)

router = APIRouter()
RULES = workshop_rules.load()
RUNS = runs_config.load()
_SIGNED_IN: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"},
    503: {"model": ErrorResponse, "description": "`unavailable`: the workshop could not be reached"}}
WRITE_ERRORS: dict[int | str, dict[str, Any]] = {
    **_SIGNED_IN, 403: {"model": ErrorResponse, "description": "`forbidden`: from another site, or not JSON"}}
BENCH_ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "`not_found`: no bench of this person's has that id"},
    422: {"model": ErrorResponse, "description": "a path or body outside its model gets FastAPI's own validation "
          "error, which is not this schema"}}


def owner_of(signed_in: Person) -> Owner:
    return Owner(signed_in.person.household_id, signed_in.person.id)


def _error(status: int, code: Literal["unavailable", "not_found", "closed", "refused"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


def unavailable() -> JSONResponse:
    return _error(503, "unavailable", "the workshop is unavailable right now; try again shortly")


def not_found() -> JSONResponse:
    return _error(404, "not_found", "no such bench")


def summary(bench: Bench) -> BenchSummary:
    return BenchSummary(id=bench.id, title=bench.title, opened_at=bench.opened_at, closed_at=bench.closed_at,
                        work=bench.work, piece_count=bench.piece_count, last_changed_at=bench.last_changed_at, thread=bench.thread)


def _piece(piece: Piece, view: BenchView, last: Run | None, installs: Mapping[int, InstallRecord],
           link_key: bytes = b"", metric: bool = False) -> BenchPiece:
    change: Change = view.changes[piece.id]
    kind = RULES.kinds.get(piece.kind)
    automation = (automation_of(view.proposals.get(piece.id), installs.get(piece.id))
                  if kind is not None and kind.format == "automation" else None)
    return BenchPiece(id=piece.id, kind=piece.kind, title=piece.text.title, body=piece.text.body,
                      piece_version=piece.version, placement=PiecePlace(order=piece.place.order, size=piece.place.size),
                      changed_by=piece.changed_by, changed_at=change.at, changed_author=change.by.author,
                      changed_person_id=change.by.person_id, last_run=None if last is None else piece_run_of(last, link_key),
                      automation=automation, video=_video(piece, kind), reader=_reader(piece, kind),
                      pointer=_pointer(piece, view),
                      file=piece_file(view.bench.household_id, piece.text.body, kind, link_key),
                      site=_site(piece, kind, view), recipe=recipe_of(piece, kind, metric))


def _video(piece: Piece, kind: Kind | None) -> PieceVideo | None:
    found = embed.video_of(piece.text.body) if kind is not None and kind.format == "video" else None
    return None if found is None else PieceVideo(provider=found.provider, url=found.url, embed_url=found.embed_url,
                                                 start=found.start)


def _site(piece: Piece, kind: Kind | None, view: BenchView) -> PieceSite | None:
    url = piece.text.body.strip()
    return site_of(view.frames.get(url)) if kind is not None and kind.format == "site" and url else None


def _reader(piece: Piece, kind: Kind | None) -> PieceReader | None:
    page = reader.page_of(piece.text.body) if kind is not None and kind.format == "reader" else None
    if page is None:
        return None
    heard = None if page.recording is None else PieceRecording(piece_id=page.recording.piece_id, starts=list(page.recording.starts))
    return PieceReader(url=page.url, title=page.title, paragraphs=list(page.paragraphs), recording=heard)


def _pointer(piece: Piece, view: BenchView) -> PiecePointer | None:
    """The piece's highlight while it is at the version it was put up against."""
    found = view.pointers.get(piece.id)
    if found is None or found.version != piece.version:
        return None
    return PiecePointer(seq=found.seq, paragraph=found.passage.paragraph, start=found.passage.start,
                        end=found.passage.end)


def _logged(row: Logged) -> LoggedCommand:
    return LoggedCommand(seq=row.seq, at=row.at, author=row.by.author, person_id=row.by.person_id,
                         type=type_of(row.command), outcome=row.outcome, piece_id=row.piece_id)


async def _work_kinds(household_id: int) -> list[WorkKind]:
    """The household's kinds of work; none while the skills cannot be read."""
    try:
        return [WorkKind(name=k.kind, label=k.label) for k in await services.get(Skills).kinds(household_id)]
    except SkillsUnavailable:
        return []


@router.get("/api/workshop/kinds", response_model=WorkshopKinds, responses={
    401: {"model": ErrorResponse, "description": "`unauthorized`: no live session"}})
async def workshop_kinds(signed_in: Person) -> WorkshopKinds:
    """200 `WorkshopKinds`; 401 `unauthorized`."""
    return await kinds_of(signed_in.person.household_id)


async def kinds_of(household_id: int) -> WorkshopKinds:
    """The piece kinds and limits of the household's benches."""
    kinds = [PieceKind(name=k.name, family=k.family, label=k.label, max_chars=k.max_chars, format=k.format,
                       language=k.language) for k in RULES.kinds.values()]
    return WorkshopKinds(kinds=kinds, sizes=list(SIZES), max_pieces=RULES.max_pieces,
                         title_max_chars=RULES.title_max_chars, run_languages=list(services.get(Sandbox).languages()),
                         run_max_chars=RUNS.max_script_chars,
                         work_kinds=await _work_kinds(household_id))


@router.get("/api/benches", response_model=BenchList, responses=_SIGNED_IN)
async def list_benches(signed_in: Person) -> BenchList | JSONResponse:
    """200 `BenchList`; 401 `unauthorized`; 503 `unavailable`."""
    try:
        benches = await services.get(Workshop).open_benches(owner_of(signed_in))
    except WorkshopUnavailable:
        return unavailable()
    return BenchList(benches=[summary(b) for b in benches])


@router.get("/api/benches/closed", response_model=BenchList, responses=_SIGNED_IN)
async def list_closed_benches(signed_in: Person) -> BenchList | JSONResponse:
    """200 `BenchList` of the closed benches, the most recently closed first; 401 `unauthorized`; 503 `unavailable`."""
    try:
        benches = await services.get(Workshop).closed_benches(owner_of(signed_in))
    except WorkshopUnavailable:
        return unavailable()
    return BenchList(benches=[summary(b) for b in benches])


@router.post("/api/benches", response_model=BenchSummary, responses={**WRITE_ERRORS, 422: BENCH_ERRORS[422]})
async def open_bench(signed_in: Person, body: BenchRequest) -> BenchSummary | JSONResponse:
    """200 `BenchSummary`, the new open bench; 401 `unauthorized`; 403 `forbidden`; 422 for a body with neither title nor
    ask; 503 `unavailable`. With an `ask`, her turn on it has begun by the time this answers (`api.bench_opening`);
    the bench is titled by `title`, else from the ask until she names it."""
    title = body.title or provisional_title(body.ask or "", RULES.title_max_chars)
    try:
        bench = await services.get(Workshop).open(owner_of(signed_in), title)
    except WorkshopUnavailable:
        return unavailable()
    if body.ask is not None:
        bench_opening.start(signed_in.person, bench.id, body.ask)
    return summary(bench)


@router.get("/api/benches/{bench_id}", response_model=BenchDetail, responses={**_SIGNED_IN, **BENCH_ERRORS})
async def read_bench(signed_in: Person, bench_id: int, request: Request) -> BenchDetail | JSONResponse:
    """200 `BenchDetail`, open or closed; 401 `unauthorized`; 404 `not_found`; 503 `unavailable`."""
    try:
        settings = request.app.state.settings
        return await detail_of(owner_of(signed_in), bench_id, services.get(DeploymentSecrets).link_key().encode(), settings.public_url)
    except BenchNotFound:
        return not_found()
    except (WorkshopUnavailable, RunsUnavailable, InstallsUnavailable):
        return unavailable()


async def detail_of(owner: Owner, bench_id: int, key: bytes, origin: str | None = None) -> BenchDetail:
    """Bench `bench_id` as `owner` sees it, its files' links minted under `key`. With an `origin` (where this page is
    reached, possibly empty), an open bench's site addresses not yet measured are measured in the background
    (`bench_frames`). Raises BenchNotFound, WorkshopUnavailable, RunsUnavailable and InstallsUnavailable."""
    view = await services.get(Workshop).read(owner, bench_id)
    if origin is not None and view.bench.closed_at is None:
        measure_in_background(owner, view, RULES, origin)
    runs = await services.get(Runs).last_on_bench(owner.household_id, bench_id)
    installs = await services.get(Installs).latest_on_bench(owner.household_id, bench_id)
    metric = await metric_of(owner.household_id)
    return BenchDetail(bench=summary(view.bench), pieces=[_piece(p, view, runs.get(p.id), installs, key, metric) for p in view.pieces],
                       recent=[_logged(r) for r in view.recent], undo_next=view.undo_next,
                       shelf=[_piece(p, view, runs.get(p.id), installs, key, metric) for p in view.shelf])


@router.post("/api/benches/{bench_id}/close", response_model=BenchSummary, responses={**WRITE_ERRORS, **BENCH_ERRORS})
async def close_bench(signed_in: Person, bench_id: int) -> BenchSummary | JSONResponse:
    """200 `BenchSummary`, closed (closing a closed bench changes nothing); 401 `unauthorized`; 403 `forbidden`;
    404 `not_found`; 503 `unavailable`."""
    try:
        bench = await services.get(Workshop).close(owner_of(signed_in), bench_id)
    except BenchNotFound:
        return not_found()
    except WorkshopUnavailable:
        return unavailable()
    return summary(bench)


@router.post("/api/benches/{bench_id}/reopen", response_model=BenchSummary, responses={**WRITE_ERRORS, **BENCH_ERRORS})
async def reopen_bench(signed_in: Person, bench_id: int) -> BenchSummary | JSONResponse:
    """200 `BenchSummary`, open again as it was closed (reopening an open bench changes nothing); 401 `unauthorized`;
    403 `forbidden`; 404 `not_found`; 503 `unavailable`."""
    try:
        bench = await services.get(Workshop).reopen(owner_of(signed_in), bench_id)
    except BenchNotFound:
        return not_found()
    except WorkshopUnavailable:
        return unavailable()
    return summary(bench)


@router.post("/api/benches/{bench_id}/commands", response_model=CommandApplied, responses={
    **WRITE_ERRORS, **BENCH_ERRORS,
    409: {"model": CommandRefused, "description": "`refused`, with the reason; logged as the bench's next seq"},
    410: {"model": ErrorResponse, "description": "`closed`: the bench is closed and takes no change"}})
async def apply_command(signed_in: Person, bench_id: int, body: CommandRequest) -> CommandApplied | JSONResponse:
    """200 `CommandApplied`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 409 `CommandRefused`; 410
    `closed`; 503 `unavailable`. An accepted install, or undo of one, is answered once it has been carried out on the
    house (`workshop.install_piece.carry_out`), however that went."""
    owner = owner_of(signed_in)
    if isinstance(body.root, AddPieceRequest) and needs_bytes(RULES, body.root.kind):
        return _error(422, "refused", "an image or file piece is made by uploading the file")
    try:
        applied = await services.get(Workshop).apply(owner, bench_id, command_of(body.root, owner.person_id, bench_id))
    except BenchNotFound:
        return not_found()
    except BenchClosed:
        return _error(410, "closed", "the bench is closed")
    except WorkshopUnavailable:
        return unavailable()
    outcome = applied.outcome
    if outcome != "accepted":
        refused = CommandRefused(code="refused", reason=outcome, seq=applied.seq, detail="the bench refused that change")
        return JSONResponse(status_code=409, content=refused.model_dump())
    await carry_out(owner, bench_id, applied)
    return CommandApplied(seq=applied.seq, piece_id=applied.piece_id)
