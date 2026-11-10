"""A bench command as it arrives on the wire, made into the Workshop's own Command, by the signed-in person."""

from ..workshop.commands import Add, Archive, Command, Edit, Install, Move, Point, Remove, Restore, Undo
from ..workshop.install_piece import automation_id_for
from ..workshop.model import By, Place, Text
from .workshop_models import (AddPieceRequest, ArchivePieceRequest, ClearHighlightRequest, EditPieceRequest, InstallPieceRequest,
                              MovePieceRequest, RemovePieceRequest, RestorePieceRequest, UndoRequest)

Request = (AddPieceRequest | RemovePieceRequest | MovePieceRequest | EditPieceRequest | ArchivePieceRequest
           | RestorePieceRequest | InstallPieceRequest | UndoRequest | ClearHighlightRequest)


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
        return Move(by, request.piece_id, Place(request.placement.order, request.placement.size))
    if isinstance(request, EditPieceRequest):
        return Edit(by, request.piece_id, request.base_version, Text(request.title, request.body))
    if isinstance(request, ArchivePieceRequest):
        return Archive(by, request.piece_id)
    if isinstance(request, RestorePieceRequest):
        return Restore(by, request.piece_id)
    return Undo(by, request.seq)
