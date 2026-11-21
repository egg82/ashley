"""What Bambuddy is sent to queue a print (`POST /api/v1/queue/`, the OpenAPI's `PrintQueueItemCreate`) from the
neutral `QueueRequest`. That route and not `POST /api/v1/library/files/add-to-queue`, whose `AddToQueueRequest` carries
only file ids, a printer and a target model: this one takes `manual_start`, `ams_mapping` and `plate_id`, which every
queued print here needs or may carry. An item is always staged (`manual_start`), so a person starts it from Bambuddy."""

from ..printing.model import Placement, QueueRequest
from . import wire

HT_FIRST = 128
"""The first AMS id of an AMS HT, whose one tray is addressed by the unit's own id; a regular unit's tray `t` is
`unit id * 4 + t` (Bambu's global tray id, the number `ams_mapping` holds)."""
_UNUSED = -1


def number(text: str) -> int | None:
    return int(text) if text.isascii() and text.isdigit() else None


def tray_of(status: wire.Status, placement: Placement) -> int | None:
    """The global tray id of the AMS slot `placement` names on the printer `status` describes, None when the printer has
    no such unit or slot."""
    if not 1 <= placement.unit <= len(status.ams):
        return None
    unit = status.ams[placement.unit - 1]
    if not any(t.id == placement.slot - 1 for t in unit.tray):
        return None
    return unit.id if unit.id >= HT_FIRST else unit.id * 4 + placement.slot - 1


def mapping_of(status: wire.Status, placements: tuple[Placement, ...]) -> list[int] | None:
    """`ams_mapping`: a list indexed by the file's filament (`need` - 1) holding the global tray id it is fed from, -1
    for a filament with no placement; None when a placement names a slot the printer lacks."""
    trays: dict[int, int] = {}
    for placement in placements:
        tray = tray_of(status, placement)
        if tray is None:
            return None
        trays[placement.need] = tray
    return [trays.get(n, _UNUSED) for n in range(1, max(trays, default=0) + 1)]


def body_of(request: QueueRequest, printer: int, file: int, mapping: list[int] | None) -> dict[str, object]:
    body: dict[str, object] = {"printer_id": printer, "library_file_id": file, "manual_start": True}
    if mapping:
        body["ams_mapping"] = mapping
    if request.plate is not None:
        body["plate_id"] = request.plate
    return body
