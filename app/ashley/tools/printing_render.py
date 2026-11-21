"""What a printing or stock tool answers, made compact from the neutral records (`ashley.printing.model`,
`ashley.stock.model`): only the fields a record has, and `cut` true when the backend holds more than was shown."""

from collections.abc import Sequence

from ..printing.model import AmsUnit, Need, Page, Placement, PrintFile, Printer, QueueRequest, Queueing, Slot, Uploading
from ..stock.model import Page as StockPage, Spool


def _set(fields: dict[str, object | None]) -> dict[str, object]:
    return {k: v for k, v in fields.items() if v is not None}


def printers(found: Page[Printer]) -> dict[str, object]:
    rows = [_set({"id": p.id, "name": p.name, "model": p.model, "online": p.online, "state": p.state, "print": p.job,
                  "percent": p.percent, "minutes_left": p.minutes_left, "layer": p.layer, "layers": p.layers,
                  "problems": [_set({"code": f.code, "text": f.text}) for f in p.faults] or None}) for p in found.rows]
    return {"printers": rows, "cut": found.total > len(rows)}


def _slot(s: Slot) -> dict[str, object]:
    return _set({"slot": s.slot, "empty": s.empty or None, "material": s.material, "colour": s.colour,
                 "percent_left": s.remaining_percent, "spool_id": s.spool_id})


def _unit(u: AmsUnit) -> dict[str, object]:
    return _set({"unit": u.unit, "humidity": u.humidity, "slots": [_slot(s) for s in u.slots]})


def ams(found: Page[Printer]) -> dict[str, object]:
    rows = [{"printer": p.name, "id": p.id, "units": [_unit(u) for u in p.ams]} for p in found.rows]
    return {"printers": rows, "cut": found.total > len(rows)}


def files(found: Page[PrintFile]) -> dict[str, object]:
    rows = [_set({"id": f.id, "name": f.name, "type": f.kind, "print_seconds": f.print_seconds, "grams": f.grams,
                  "sliced_for": f.printer_model, "prints": f.prints}) for f in found.rows]
    return {"files": rows, "matched": found.total, "cut": found.total > len(rows)}


def needs(found: Sequence[Need]) -> dict[str, object]:
    return {"filaments": [_set({"slot": n.slot, "type": n.material, "colour": n.colour, "grams": n.grams})
                          for n in found]}


def spools(found: StockPage[Spool]) -> dict[str, object]:
    rows = [_set({"id": s.id, "material": s.material, "brand": s.brand, "colour_name": s.colour_name,
                  "colour": s.colour, "grams_left": s.remaining_grams, "grams_full": s.full_grams,
                  "location": s.location}) for s in found.rows]
    return {"spools": rows, "cut": found.total > len(rows)}


def queued(done: Queueing) -> dict[str, object]:
    """What became of a queued print: `outcome` (`queued`, `not_found`, `rejected`), and for a queued one its entry's id
    and place, and that it is staged."""
    return _set({"outcome": done.outcome, "item_id": done.item_id, "position": done.position,
                 "staged": True if done.outcome == "queued" else None})


def uploaded(done: Uploading) -> dict[str, object]:
    """What became of an upload: `outcome` (`uploaded`, `rejected`), the library file's id, and whether the library
    already held the file."""
    return _set({"outcome": done.outcome, "file_id": done.file_id, "already_there": done.already_there or None})


def _slot_at(printer: Printer, placement: Placement) -> Slot | None:
    unit = next((u for u in printer.ams if u.unit == placement.unit), None)
    return None if unit is None else next((s for s in unit.slots if s.slot == placement.slot), None)


def _duration(seconds: int | None) -> str:
    if seconds is None:
        return "an unknown time"
    minutes = max(1, round(seconds / 60))
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def _feed(printer: Printer, placement: Placement, needs: Sequence[Need]) -> str | None:
    """One filament's line, None when the printer has no such slot or the file no such filament."""
    slot, need = _slot_at(printer, placement), next((n for n in needs if n.slot == placement.need), None)
    if slot is None or need is None:
        return None
    held = slot.material or "empty"
    differs = need.material is not None and slot.material is not None and need.material.lower() != slot.material.lower()
    return (f"filament {placement.need} from AMS {placement.unit} slot {placement.slot} ({held})"
            f"{', not the type the file is sliced for' if differs else ''}")


def queuing(file: PrintFile, printer: Printer, request: QueueRequest, needs: Sequence[Need]) -> str | None:
    """The line the person agrees to before the print is queued: the library file by its id, type, print time and grams
    (never its name, which is written outside the household), the printer by the name the household gave it, each
    placement against what the printer says is in the slot, and that it waits staged. None when a placement names a slot
    the printer lacks or a filament the file does not need."""
    feeds = [_feed(printer, p, needs) for p in request.placements]
    if any(f is None for f in feeds):
        return None
    grams = "" if file.grams is None else f", {file.grams:g} g"
    plate = "" if request.plate is None else f", plate {request.plate}"
    placed = "" if not feeds else "; " + "; ".join(f for f in feeds if f is not None)
    return (f"Queue library file {file.id} ({file.kind or 'unknown type'}, {_duration(file.print_seconds)}{grams}) on "
            f"{printer.name}{plate}{placed}. It waits, staged, until someone starts it in Bambuddy")
