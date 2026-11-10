"""A person's press of Run on a code piece of their bench (`ashley.workshop.run_piece.run_piece`): the same Run command
her `bench_run` makes, logged on the bench, then the piece run once. The request is answered once the run has ended;
every screen of theirs reads the bench back when `LiveBench` says so, the run's result on the piece included."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..runs.runs import RunsUnavailable
from ..workshop.commands import Run
from ..workshop.model import By
from ..workshop.run_piece import CannotRun, run_piece
from ..workshop.workshop import BenchClosed, BenchNotFound, WorkshopUnavailable
from .bench_run_models import RunApplied, RunRequest, output_of
from .benches import BENCH_ERRORS, WRITE_ERRORS, not_found, owner_of, unavailable
from .models import ErrorResponse
from .person import Person
from .workshop_models import CommandRefused

router = APIRouter()
CANNOT: dict[Literal["language", "blank", "too_long"], str] = {
    "language": "that language cannot be run here", "blank": "the piece holds no code to run",
    "too_long": "the piece is longer than run_max_chars"}


@router.post("/api/benches/{bench_id}/runs", response_model=RunApplied, responses={
    **WRITE_ERRORS, **BENCH_ERRORS,
    409: {"model": CommandRefused, "description": "`refused`, with the reason (`not_runnable` for a piece that is "
          "not code, `stale_base`, `no_such_piece`); logged as the bench's next seq"},
    410: {"model": ErrorResponse, "description": "`closed`: the bench is closed and runs nothing"}})
async def run_bench_piece(signed_in: Person, bench_id: int, body: RunRequest, request: Request) -> RunApplied | JSONResponse:
    """200 `RunApplied`, once the run has ended, however it ended; 401 `unauthorized`; 403 `forbidden`; 404
    `not_found`; 409 `CommandRefused`; 410 `closed`; 422 `refused` for a language not in `run_languages`, or a piece
    blank or longer than `run_max_chars`, before anything is logged; 503 `unavailable` (nothing ran)."""
    owner = owner_of(signed_in)
    command = Run(By(owner.person_id), body.piece_id, body.base_version, body.run_language)
    try:
        got = await run_piece(owner, bench_id, command)
    except CannotRun as e:
        return JSONResponse(status_code=422, content=ErrorResponse(code="refused", detail=CANNOT[e.why]).model_dump())
    except BenchNotFound:
        return not_found()
    except BenchClosed:
        return JSONResponse(status_code=410, content=ErrorResponse(code="closed", detail="the bench is closed")
                            .model_dump())
    except (WorkshopUnavailable, RunsUnavailable):
        return unavailable()
    applied = got.applied
    if applied.outcome != "accepted":
        refused = CommandRefused(code="refused", reason=applied.outcome, seq=applied.seq,
                                 detail="the bench refused that run")
        return JSONResponse(status_code=409, content=refused.model_dump())
    if got.finished is None:
        return unavailable()
    assert applied.piece_id is not None
    done = got.finished
    key = request.app.state.settings.files_link_key.encode()
    return RunApplied(seq=applied.seq, piece_id=applied.piece_id, run_id=done.run_id,
                      run_output=output_of(done.output, owner.household_id, done.artifacts, done.inputs, key))
