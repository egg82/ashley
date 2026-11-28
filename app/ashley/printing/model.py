"""The household's 3D printing as she sees it, whichever manager runs the printers: plain records whose fields are stated
in printing terms. An adapter (for Bambuddy, `ashley.bambuddy.printing`) fills them from its backend's own shapes; nothing
outside it knows those shapes."""

from dataclasses import dataclass
from typing import Literal

Reason = Literal["refused", "unreachable", "unrecognised"]
"""Why a read failed: `refused`, the backend turned the household's key away (or the key lacks a permission the read
needs); `unreachable`, no answer in time or a server error; `unrecognised`, what answered is not that backend's API."""


@dataclass(frozen=True)
class Slot:
    """One filament slot of an AMS unit: `slot` counts from 1, `material` is the filament type the slot holds ("PLA"),
    `colour` its hex colour ("#RRGGBB"), `remaining_percent` how much of the spool is left (None when the printer does
    not know), and `spool_id` the stock spool the household says is loaded (`ashley.stock.model.Spool.id`; None when none
    is recorded for the slot). An empty slot has no material, colour or remaining amount."""

    slot: int
    material: str | None
    colour: str | None
    remaining_percent: int | None
    spool_id: str | None
    empty: bool


@dataclass(frozen=True)
class AmsUnit:
    """One AMS unit of a printer: `unit` counts from 1, `humidity` is the unit's relative humidity in percent as the backend
    passes it on, and None when it reports none."""

    unit: int
    humidity: int | None
    slots: tuple[Slot, ...]


@dataclass(frozen=True)
class Fault:
    """A problem a printer reports: its `code` and the backend's `text` for it when it has one."""

    code: str
    text: str | None


@dataclass(frozen=True)
class Printer:
    """A printer the household has. `id` is the backend's, `name` what the household calls it, `online` whether the
    backend can reach it. `state` is the backend's word for what it is doing (`RUNNING`, `IDLE`, `PAUSE`, `FINISH`,
    `FAILED`, as the printer says them), None when it says nothing. `job` is the name of the print it is on, `percent` how
    far along that print is (0 to 100), `minutes_left` the time it expects to need, `layer` and `layers` where it is in it;
    each None when there is no print or the printer does not say. `faults` are the problems it reports now, `ams` its
    AMS units, empty for a printer with none."""

    id: str
    name: str
    model: str | None
    online: bool
    state: str | None
    job: str | None
    percent: float | None
    minutes_left: int | None
    layer: int | None
    layers: int | None
    faults: tuple[Fault, ...]
    ams: tuple[AmsUnit, ...]


@dataclass(frozen=True)
class PrintFile:
    """A file in the household's print library: `id` as `Printing.needs` takes it, `name` the model's name (or the file's),
    `kind` the file's type (`3mf`, `gcode`), `print_seconds` how long its slice takes to print, `grams` the filament it
    uses in all, `printer_model` the printer it was sliced for, `prints` how many times it has been printed. A field the
    backend leaves out is None."""

    id: str
    name: str
    kind: str | None
    print_seconds: int | None
    grams: float | None
    printer_model: str | None
    prints: int


@dataclass(frozen=True)
class Need:
    """One filament a file needs: the `slot` of the project (from 1), the `material` and hex `colour` it is sliced with,
    and the `grams` it uses; each None when the file does not say."""

    slot: int
    material: str | None
    colour: str | None
    grams: float | None


@dataclass(frozen=True)
class Placement:
    """Where one filament of a file is to come from: the file's filament `need` (`Need.slot`, from 1) is fed from AMS
    `unit` (`AmsUnit.unit`, from 1), `slot` (`Slot.slot`, from 1) of the printer it is queued on."""

    need: int
    unit: int
    slot: int


@dataclass(frozen=True)
class QueueRequest:
    """A print to queue: library file `file_id` on printer `printer_id`, its filaments fed as `placements` say (a need
    with no placement is left to the manager), `plate` the plate of a multi-plate file to print (from 1; None for the
    manager's choice). It is always staged: it waits in the queue until a person starts it."""

    file_id: str
    printer_id: str
    placements: tuple[Placement, ...] = ()
    plate: int | None = None


Queued = Literal["queued", "not_found", "rejected"]
"""What became of a queued print: `queued`; `not_found`, the file or the printer is not the household's; `rejected`, the
manager would not queue it (a file that is not sliced, a filament the printer cannot supply, a placement it does not
accept)."""


@dataclass(frozen=True)
class Queueing:
    """What `Printing.queue` did: the outcome, and the queue entry's `item_id` and `position` (from 1, None when the
    manager does not say) when it is `queued`."""

    outcome: Queued
    item_id: str | None = None
    position: int | None = None


Cancelled = Literal["cancelled", "gone"]
"""What became of a cancel of a queued print: `cancelled`, it left the queue without printing; `gone`, the manager has no
such entry waiting (it was started, finished, cancelled already, or removed), so nothing was changed."""


Uploaded = Literal["uploaded", "rejected"]
"""What became of an uploaded file: `uploaded`, now in the library (`already_there` when the library already held the same
file, and `file_id` is that one); `rejected`, the manager would not take it (a type or size it does not accept)."""


@dataclass(frozen=True)
class Uploading:
    """What `Printing.upload` did: the outcome and the library file's `file_id` as `Printing.files` gives it."""

    outcome: Uploaded
    file_id: str | None = None
    already_there: bool = False


@dataclass(frozen=True)
class Page[T]:
    """What one read holds, and `total`, how many the backend holds in all."""

    rows: tuple[T, ...]
    total: int


class PrintingFailed(Exception):
    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason: Reason = reason


class PrintingUnavailable(Exception):
    """The household's link to its printing manager cannot be read."""


class NotConnected(Exception):
    """The household has no printing manager."""
