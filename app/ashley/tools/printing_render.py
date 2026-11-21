"""What a printing or stock tool answers, made compact from the neutral records (`ashley.printing.model`,
`ashley.stock.model`): only the fields a record has, and `cut` true when the backend holds more than was shown."""

from collections.abc import Sequence

from ..printing.model import AmsUnit, Need, Page, PrintFile, Printer, Slot
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
