"""A person's tap on an option of a choice row shown beside her reply (`WireFact`): an ordinary Edit of the measurements
piece by the person (`workshop.choice_tap.tapped`), logged and undoable like any, then a `Surfaced` of theirs naming the
row as it now is, so the value they chose is not shown back to them. Only the bench's owner taps; anyone else's bench
is 404 as one that does not exist."""

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import services
from ..workshop import measurements
from ..workshop.choice_tap import tapped
from ..workshop.commands import Edit, ShownRow, Surfaced
from ..workshop.model import By, Text
from ..workshop.workshop import BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from .benches import BENCH_ERRORS, WRITE_ERRORS, not_found, owner_of, unavailable
from .models import ErrorResponse
from .person import Person
from .workshop_models import CommandRefused

router = APIRouter()


class ChoiceRequest(BaseModel):
    """The option tapped: one of the row's `options`."""

    value: str = Field(min_length=1, max_length=measurements.MAX_VALUE)


class ChoiceSet(BaseModel):
    """The row is set: `seq` is the Edit that set it, null when it already held `value` as the person's and nothing
    changed."""

    seq: int | None


def _error(status: int, code: Literal["not_found", "refused", "closed"], detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(code=code, detail=detail).model_dump())


@router.put("/api/benches/{bench_id}/pieces/{piece_id}/choices/{name}", response_model=ChoiceSet, responses={
    **WRITE_ERRORS, **BENCH_ERRORS,
    404: {"model": ErrorResponse, "description": "`not_found`: no bench of this person's has that id, or no piece on its "
          "layout holds a choice row of that name"},
    409: {"model": CommandRefused, "description": "`refused`, with the reason (`stale_base` when the piece changed "
          "between the read and the edit: tap again); logged as the bench's next seq"},
    410: {"model": ErrorResponse, "description": "`closed`: the bench is closed and takes no change"}})
async def set_choice(signed_in: Person, bench_id: int, piece_id: int, name: str, body: ChoiceRequest
                     ) -> ChoiceSet | JSONResponse:
    """200 `ChoiceSet`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 409 `CommandRefused`; 410 `closed`; 422
    `refused` for a value that is not one of the row's options, before anything is logged; 503 `unavailable`."""
    owner = owner_of(signed_in)
    by = By(owner.person_id)
    shop = services.get(Workshop)
    try:
        view = await shop.read(owner, bench_id)
        piece = next((p for p in view.pieces if p.id == piece_id), None)
        got = "no_row" if piece is None else tapped(piece.text.body, name, body.value)
        if got == "no_row" or piece is None:
            return _error(404, "not_found", "no such choice on this bench")
        if got == "off_options":
            return _error(422, "refused", "that is not one of the choice's options")
        if got == piece.text.body:
            return ChoiceSet(seq=None)
        applied = await shop.apply(owner, bench_id, Edit(by, piece.id, piece.version, Text(piece.text.title, got)))
        if applied.outcome != "accepted":
            refused = CommandRefused(code="refused", reason=applied.outcome, seq=applied.seq,
                                     detail="the bench refused that change")
            return JSONResponse(status_code=409, content=refused.model_dump())
        await shop.apply(owner, bench_id, Surfaced(by, piece.id, (ShownRow(name, body.value),)))
    except BenchNotFound:
        return not_found()
    except BenchClosed:
        return _error(410, "closed", "the bench is closed")
    except WorkshopUnavailable:
        return unavailable()
    return ChoiceSet(seq=applied.seq)
