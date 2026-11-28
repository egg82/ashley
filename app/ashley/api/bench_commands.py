"""A bench command as it arrives on the wire, made into the Workshop's own Command, by the signed-in person."""

from ..workshop.commands import KEEP, Add, Archive, Command, Edit, Install, Link, Move, Point, Remove, Restore, Undo, Unlink
from ..workshop.install_piece import automation_id_for
from ..workshop.model import Box, By, Pin, Place, Text
from .workshop_models import (AddPieceRequest, ArchivePieceRequest, ClearHighlightRequest, EditPieceRequest, InstallPieceRequest,
                              LinkRequest, MovePieceRequest, RemovePieceRequest, RestorePieceRequest, UndoRequest, UnlinkRequest)

Request = (AddPieceRequest | RemovePieceRequest | MovePieceRequest | EditPieceRequest | ArchivePieceRequest
           | RestorePieceRequest | InstallPieceRequest | UndoRequest | ClearHighlightRequest | LinkRequest | UnlinkRequest)


def command_of(request: Request, person_id: int, bench_id: int) -> Command:
    by = By(person_id)
    if isinstance(request, InstallPieceRequest):
        return Install(by, request.piece_id, request.proposal, automation_id_for(bench_id, request.piece_id))
    if isinstance(request, ClearHighlightRequest):
        return Point(by, request.piece_id, request.base_version, None)
    if isinstance(request, AddPieceRequest):
        return Add(by, request.kind, Text(request.title, request.body), request.size)
    if isinstance(request, RemovePieceRequest):
        return Remove(by, request.piece_id)
    if isinstance(request, MovePieceRequest):
        return _move(by, request)
    if isinstance(request, EditPieceRequest):
        return Edit(by, request.piece_id, request.base_version, Text(request.title, request.body))
    if isinstance(request, ArchivePieceRequest):
        return Archive(by, request.piece_id)
    if isinstance(request, RestorePieceRequest):
        return Restore(by, request.piece_id)
    if isinstance(request, (LinkRequest, UnlinkRequest)):
        return (Link if isinstance(request, LinkRequest) else Unlink)(by, request.from_id, request.kind, request.to_id)
    return Undo(by, request.seq)


def _move(by: By, request: MovePieceRequest) -> Move:
    """The person's move: a `pin` or `box` left out of the placement keeps the piece's, a null clears it."""
    placement, given = request.placement, request.placement.model_fields_set
    pin = None if placement.pin is None else Pin(placement.pin.x, placement.pin.y)
    box = None if placement.box is None else Box(placement.box.w, placement.box.h)
    return Move(by, request.piece_id, Place(placement.order, placement.size), pin if "pin" in given else KEEP,
                box if "box" in given else KEEP)
