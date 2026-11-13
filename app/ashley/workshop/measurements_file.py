"""The measurements a model run starts with: the bench's measurements pieces merged into the one `measurements.json`
that `ashley_cad.measured` and `ashley_cad.chosen` read, `{"items": [...]}`, each row as its piece wrote it."""

import json
from collections.abc import Iterable

from .measurements import CHOICE, Choice, Row, items_of

NAME = "measurements.json"


def file_of(bodies: Iterable[str]) -> str | None:
    """The file for the measurements pieces whose bodies are `bodies`, in order; a name a later piece repeats keeps its
    first value. None when they hold no row."""
    items: dict[str, dict[str, object]] = {}
    for body in bodies:
        for m in items_of(body) or ():
            items.setdefault(m.name, _item(m))
    return json.dumps({"items": list(items.values())}, separators=(",", ":")) if items else None


def _item(m: Row) -> dict[str, object]:
    if isinstance(m, Choice):
        one: dict[str, object] = {"kind": CHOICE, "name": m.name, "label": m.label, "value": m.value, "source": m.source}
        optional: dict[str, object | None] = {"options": list(m.options) or None, "turn": m.turn, "piece": m.piece,
                                              "ref": m.ref}
    else:
        one = {"name": m.name, "value": m.value, "unit": m.unit, "source": m.source}
        optional = {"tolerance": m.tolerance, "ref": m.ref, "given": m.given}
    return {**one, **{k: v for k, v in optional.items() if v is not None}}
