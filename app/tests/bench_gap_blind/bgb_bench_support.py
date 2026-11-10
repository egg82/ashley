"""A bench with household pieces and an outside one, and the turn's bench talk, for the bench-view and main-chat tests."""

from dataclasses import replace

from ashley.workshop.model import HER, Change, Piece, Place, Text
from bench_tools_support import EPOCH, FakeWorkshop
from respond_support import ALANA, inbound

TITLE_MARK = "OUTSIDE-TITLE-MARK-5521"
BODY_MARK = "OUTSIDE-BODY-MARK-8830"
BODY_OPENING = "CLIP-HOLDER-OPENING-TEXT"


def piece(pid: int, kind: str, title: str, body: str, version: int = 1, order: int = 0, outside: bool = False) -> Piece:
    return Piece(pid, kind, Text(title, body), version, Place(order, "medium"), pid, outside)


NOTE = piece(3, "note", "Plan for the gate", "Gate plan. " * 30, version=4, order=0)
MODEL = piece(5, "model", "Holder model", BODY_OPENING + " rest of the script " * 40, version=7, order=1)
IMAGE = piece(9, "image", TITLE_MARK, BODY_MARK, version=2, order=2)
READER = piece(8, "reader", TITLE_MARK + " reader", BODY_MARK + " page text", version=3, order=3)
FLAGGED = piece(6, "note", TITLE_MARK + " flagged", BODY_MARK, version=1, order=4, outside=True)


def workshop(*pieces: Piece) -> FakeWorkshop:
    return FakeWorkshop(pieces=pieces, changes={p.id: Change(EPOCH, HER) for p in pieces})


BENCH = replace(inbound(thread="bench:4", speaker_id=ALANA.id, kind="brainstorm"), audience="owner", shared=False,
                place=None, channel="web", bench_id=4, later=True, later_by="turn")
