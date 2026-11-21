"""The print-queue and upload tools as the model sees them, and their arguments checked. `printing_queue` changes the
household's queue, so it is an `asks` change, held for the person's OK in every turn (`ashley.tools.outside`);
`printing_upload` adds a file to the household's print library and is `judged`: it starts nothing and a library file is
deleted in Bambuddy, so a turn that has read outside words has the action judge decide it, where queuing a print is
always agreed to first. Neither returns text written outside the household."""

import re
from typing import Any

from ..inference.model import ToolSpec
from ..printing.model import Placement, QueueRequest
from .printing_config import PrintingConfig

QUEUE = "printing_queue"
UPLOAD = "printing_upload"

_ID = re.compile(r"^[0-9]{1,12}$")
MODEL_SUFFIXES = (".stl", ".3mf")
"""What a bench file may be to go to the library: the two kinds of printable model a bench holds."""

QUEUE_INSTRUCTIONS = ("printing_queue puts a library file in a printer's queue, by the ids printing_files and "
                      "printing_printers give. It is never started by you: it waits in Bambuddy, staged, until a person "
                      "starts it at the printer, and only a file that is sliced for the printer can be queued. Say which "
                      "AMS slot should feed each of the file's filaments (from printing_needs and printing_ams) in "
                      "slots; a filament with no slot is left for Bambuddy to choose. A queued print never happens "
                      "straight away: it is shown to the person and waits for their OK, so say that it is waiting, not "
                      "that it is queued.")
UPLOAD_INSTRUCTIONS = ("printing_upload puts a bench's STL or 3MF file piece in the print library, and answers with the "
                       "library file's id, which printing_queue takes. Bambuddy queues only a sliced file, so an STL or "
                       "an unsliced 3MF is for the person to slice there first.")


def queue_spec(config: PrintingConfig) -> ToolSpec:
    slots = {"type": "array", "maxItems": config.placements_max, "items": {
        "type": "object", "properties": {
            "need": {"type": "integer", "minimum": 1, "description": "the file's filament, by the slot printing_needs gives"},
            "unit": {"type": "integer", "minimum": 1, "description": "the AMS unit, as printing_ams gives it"},
            "slot": {"type": "integer", "minimum": 1, "description": "the slot of that unit"}},
        "required": ["need", "unit", "slot"]},
             "description": "which AMS slot feeds each filament you have an opinion on"}
    queue = {"type": "object", "properties": {
        "file_id": {"type": "string", "description": "the library file, by the id printing_files gives"},
        "printer_id": {"type": "string", "description": "the printer, by the id printing_printers gives"},
        "slots": slots,
        "plate": {"type": "integer", "minimum": 1, "description": "the plate of a multi-plate file; omit for Bambuddy's choice"}},
             "required": ["file_id", "printer_id"]}
    return ToolSpec(QUEUE, "Put a library file in a printer's queue, staged: a person starts it from Bambuddy.", queue,
                    reads=False, outside=False, tier="asks", label="Queued a print in Bambuddy")


def upload_spec() -> ToolSpec:
    upload = {"type": "object", "properties": {
        "piece": {"type": "integer", "description": "the bench's STL or 3MF file piece, by its id"}}, "required": ["piece"]}
    return ToolSpec(UPLOAD, "Add this bench's STL or 3MF file piece to the print library, so it can be queued; its "
                    "library id is the answer.", upload, reads=False, outside=False, tier="judged",
                    label="Added a file to the print library")


def queue_request(arguments: dict[str, object], config: PrintingConfig) -> QueueRequest | str:
    """The print `printing_queue`'s arguments ask for, or the reason they are wrong, which names no value."""
    file, printer = arguments.get("file_id"), arguments.get("printer_id")
    if not isinstance(file, str) or not _ID.match(file):
        return "file_id is an id as printing_files gives it"
    if not isinstance(printer, str) or not _ID.match(printer):
        return "printer_id is an id as printing_printers gives it"
    plate = _positive(arguments.get("plate"))
    if arguments.get("plate") is not None and plate is None:
        return "plate is a whole number from 1"
    placements = _placements(arguments.get("slots"), config)
    if isinstance(placements, str):
        return placements
    return QueueRequest(file, printer, placements, plate)


def _placements(given: object, config: PrintingConfig) -> tuple[Placement, ...] | str:
    if given is None:
        return ()
    wrong = f"slots is a list of at most {config.placements_max} of need, unit and slot, each a whole number from 1"
    loose: Any = given
    if not isinstance(given, list):
        return wrong
    entries = list[object](loose)
    if len(entries) > config.placements_max:
        return wrong
    found: list[Placement] = []
    for entry in entries:
        loose_entry: Any = entry
        if not isinstance(entry, dict):
            return wrong
        fields = dict[object, object](loose_entry)
        need, unit, slot = _positive(fields.get("need")), _positive(fields.get("unit")), _positive(fields.get("slot"))
        if need is None or unit is None or slot is None:
            return wrong
        if any(p.need == need for p in found):
            return "each filament is named once in slots"
        found.append(Placement(need, unit, slot))
    return tuple(found)


def _positive(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


def upload_piece(arguments: dict[str, object]) -> int | str:
    """The bench piece `printing_upload` names, or the reason the argument is wrong."""
    return _positive(arguments.get("piece")) or "piece is a whole number, a piece's id"
