"""A person takes back her whole turn on their bench: `Workshop.undo_turn`, all or nothing."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import services
from ..workshop.model import By
from ..workshop.workshop import BenchClosed, BenchNotFound, Workshop, WorkshopUnavailable
from .benches import BENCH_ERRORS, WRITE_ERRORS, not_found, owner_of, unavailable
from .models import ErrorResponse
from .person import Person
from .workshop_models import TurnRefusal, TurnRefused, TurnUndone, UndoTurnRequest

router = APIRouter()


@router.post("/api/benches/{bench_id}/undo-turn", response_model=TurnUndone, responses={
    **WRITE_ERRORS, **BENCH_ERRORS,
    409: {"model": TurnRefused, "description": "`refused`: nothing was undone, and every refusal is listed"},
    410: {"model": ErrorResponse, "description": "`closed`: the bench is closed and takes no change"}})
async def undo_turn(signed_in: Person, bench_id: int, body: UndoTurnRequest) -> TurnUndone | JSONResponse:
    """200 `TurnUndone`; 401 `unauthorized`; 403 `forbidden`; 404 `not_found`; 409 `TurnRefused`; 410 `closed`; 503
    `unavailable`. Her turns make no install, so nothing is carried out on the house."""
    owner = owner_of(signed_in)
    try:
        done = await services.get(Workshop).undo_turn(owner, bench_id, By(owner.person_id), body.seq)
    except BenchNotFound:
        return not_found()
    except BenchClosed:
        return JSONResponse(status_code=410, content=ErrorResponse(code="closed", detail="the bench is closed").model_dump())
    except WorkshopUnavailable:
        return unavailable()
    if done.refused:
        refused = TurnRefused(code="refused", reason=done.refused[0][1], detail="nothing was undone",
                              refused=[TurnRefusal(seq=s, reason=r) for s, r in done.refused])
        return JSONResponse(status_code=409, content=refused.model_dump())
    return TurnUndone(undone=list(done.undone))
