"""Bambuddy as the household's Printing (`ashley.printing.printing`): its printers with what each is doing and its AMS
units (`GET /api/v1/printers/` then `GET /api/v1/printers/:id/status` for each), which spool the household says sits in
each slot (`GET /api/v1/spoolman/inventory/slot-assignments/all`), the print library (`GET /api/v1/library/files`) and one
file's filament needs (`GET /api/v1/library/files/:id/filament-requirements`), turned from `wire`'s shapes into the
printing records; and its two writes, a print put in the queue staged (`POST /api/v1/queue/`, `queueing`) and a file
added to the library (`POST /api/v1/library/files`). Every answered call moves the connection's `checked_at`. Nothing outside this module, `wire` and
`colour` knows Bambuddy's field names. A read that cannot say which spool is in a slot (Bambuddy has no Spoolman) logs
`bambuddy.assignments_skipped` with the connection id and leaves `Slot.spool_id` None."""

import asyncio
import logging
from urllib.parse import quote

from .. import logs
from ..connections.model import Opened
from ..printing.model import (AmsUnit, Fault, NotConnected, Need, Page, PrintFile, Printer, PrintingFailed,
                              PrintingUnavailable, QueueRequest, Queueing, Reason, Slot, Uploading)
from ..printing.printing import Printing
from . import queueing, wire
from .client import Reason as BambuddyReason
from .colour import hex_of
from .read import Reader

log = logging.getLogger("ashley.bambuddy")
_REASON: dict[BambuddyReason, Reason] = {"refused": "refused", "unreachable": "unreachable",
                                         "not_bambuddy": "unrecognised", "not_found": "unrecognised",
                                         "rejected": "unrecognised"}
_READER = Reader("printing", PrintingUnavailable, NotConnected, lambda r: PrintingFailed(_REASON[r]))
_Held = dict[tuple[int, int, int], str]
"""The spool id of each (printer, AMS unit, tray) the household has recorded."""


class BambuddyPrinting(Printing):
    async def connected(self, household_id: int) -> bool:
        return await _READER.opened(household_id) is not None

    async def printers(self, household_id: int, limit: int) -> Page[Printer]:
        opened = await _READER.need(household_id)
        listed = await _READER.get(opened, "/api/v1/printers/", {}, wire.Printers)
        if listed is None:
            raise PrintingFailed("unrecognised")
        shown = listed.root[:limit]
        held = await _assignments(opened)
        statuses = await asyncio.gather(*(_status(opened, p.id) for p in shown))
        return Page(tuple(_printer_from(p, s, held) for p, s in zip(shown, statuses, strict=True)), len(listed.root))

    async def files(self, household_id: int, search: str | None, limit: int) -> Page[PrintFile]:
        opened = await _READER.need(household_id)
        got = await _READER.get(opened, "/api/v1/library/files", {"include_root": False}, wire.Files)
        if got is None:
            raise PrintingFailed("unrecognised")
        words = search.lower() if search else None
        found = sorted((f for f in got.root if words is None or words in _name(f).lower() or words in f.filename.lower()),
                       key=lambda f: f.created_at, reverse=True)
        return Page(tuple(_file_from(f) for f in found[:limit]), len(found))

    async def needs(self, household_id: int, file_id: str) -> tuple[Need, ...] | None:
        opened = await _READER.need(household_id)
        got = await _READER.get(opened, f"/api/v1/library/files/{quote(file_id, safe='')}/filament-requirements", {},
                                wire.Requirements)
        if got is None:
            return None
        return tuple(Need(slot=f.slot_id, material=f.type, colour=hex_of(f.color), grams=f.used_grams)
                     for f in got.filaments)

    async def file(self, household_id: int, file_id: str) -> PrintFile | None:
        opened = await _READER.need(household_id)
        if (number := queueing.number(file_id)) is None:
            return None
        got = await _READER.get(opened, f"/api/v1/library/files/{number}", {}, wire.File)
        return None if got is None else _file_from(got)

    async def queue(self, household_id: int, request: QueueRequest) -> Queueing:
        opened = await _READER.need(household_id)
        printer, file = queueing.number(request.printer_id), queueing.number(request.file_id)
        if printer is None or file is None:
            return Queueing("not_found")
        mapping = None
        if request.placements:
            status = await _READER.get(opened, f"/api/v1/printers/{printer}/status", {}, wire.Status)
            if status is None:
                return Queueing("not_found")
            if (mapping := queueing.mapping_of(status, request.placements)) is None:
                return Queueing("rejected")
        put = await _READER.post(opened, "/api/v1/queue/", queueing.body_of(request, printer, file, mapping),
                                 wire.QueueItem)
        if isinstance(put, str):
            return Queueing(put)
        return Queueing("queued", str(put.id), put.position)

    async def upload(self, household_id: int, name: str, data: bytes) -> Uploading:
        opened = await _READER.need(household_id)
        put = await _READER.upload(opened, "/api/v1/library/files", name, data, wire.Upload)
        if put == "not_found":
            raise PrintingFailed("unrecognised")
        if put == "rejected":
            return Uploading("rejected")
        assert not isinstance(put, str)
        return Uploading("uploaded", str(put.duplicate_of or put.id), put.duplicate_of is not None)


async def _status(opened: Opened, printer_id: int) -> wire.Status:
    got = await _READER.get(opened, f"/api/v1/printers/{printer_id}/status", {}, wire.Status)
    if got is None:
        raise PrintingFailed("unrecognised")
    return got


async def _assignments(opened: Opened) -> _Held:
    try:
        got = await _READER.get(opened, "/api/v1/spoolman/inventory/slot-assignments/all", {}, wire.Assignments)
    except PrintingFailed as e:
        logs.warning(log, "bambuddy.assignments_skipped", connection=opened.connection.id, reason=e.reason)
        return {}
    if got is None:
        logs.warning(log, "bambuddy.assignments_skipped", connection=opened.connection.id, reason="not_found")
        return {}
    return {(a.printer_id, a.ams_id, a.tray_id): str(a.spoolman_spool_id) for a in got.root}


def _printer_from(p: wire.Printer, s: wire.Status, held: _Held) -> Printer:
    job = s.subtask_name or s.current_print
    return Printer(
        id=str(p.id), name=p.name, model=p.model, online=s.connected, state=s.state, job=job or None,
        percent=s.progress if job else None, minutes_left=s.remaining_time if job else None,
        layer=s.layer_num if job else None, layers=s.total_layers if job else None,
        faults=tuple(Fault(h.full_code or h.code, h.description) for h in s.hms_errors),
        ams=tuple(_unit_from(p.id, n, u, held) for n, u in enumerate(s.ams, 1)))


def _unit_from(printer_id: int, number: int, u: wire.Unit, held: _Held) -> AmsUnit:
    return AmsUnit(unit=number, humidity=u.humidity,
                   slots=tuple(_slot_from(t, held.get((printer_id, u.id, t.id))) for t in u.tray))


def _slot_from(t: wire.Tray, spool_id: str | None) -> Slot:
    empty = t.exists is False or not t.tray_type
    return Slot(slot=t.id + 1, material=None if empty else t.tray_type, colour=None if empty else hex_of(t.tray_color),
                remaining_percent=t.remain if not empty and t.remain is not None and 0 <= t.remain <= 100 else None,
                spool_id=spool_id, empty=empty)


def _name(f: wire.File) -> str:
    return f.print_name or f.filename


def _file_from(f: wire.File) -> PrintFile:
    return PrintFile(id=str(f.id), name=_name(f), kind=f.file_type, print_seconds=f.print_time_seconds,
                     grams=f.filament_used_grams, printer_model=f.sliced_for_model, prints=f.print_count)
