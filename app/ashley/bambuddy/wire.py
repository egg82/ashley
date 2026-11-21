"""The parts of Bambuddy's JSON bodies she reads, as its OpenAPI document (v1.3.1) writes them: `PrinterResponse`,
`PrinterStatus` with its `AMSUnit`, `AMSTray` and `HMSErrorResponse`, `SpoolResponse` (the shape the spoolman inventory
routes document as `InventorySpool`), `SpoolmanSlotAssignmentEnriched`, `FileListResponse`, `FileUploadResponse` and `PrintQueueItemResponse`. The document gives
`GET /printers/`, the spoolman inventory spools and a file's filament requirements no response schema; those are read as
the shapes its descriptions name, every field they might leave out optional. Fields she does not read are ignored.
`parsed` turns a body into one of these or raises BambuddyFailed (`not_bambuddy`)."""

from typing import TypeVar

from pydantic import BaseModel, RootModel, ValidationError

from .client import BambuddyFailed


class Printer(BaseModel):
    id: int
    name: str
    model: str | None = None
    is_active: bool = True


class Printers(RootModel[list[Printer]]):
    pass


class Tray(BaseModel):
    id: int
    tray_color: str | None = None
    tray_type: str | None = None
    remain: int | None = None
    exists: bool | None = None


class Unit(BaseModel):
    id: int
    humidity: int | None = None
    tray: list[Tray] = []


class Hms(BaseModel):
    code: str
    full_code: str | None = None
    description: str | None = None


class Status(BaseModel):
    id: int
    name: str
    connected: bool
    state: str | None = None
    subtask_name: str | None = None
    current_print: str | None = None
    progress: float | None = None
    remaining_time: int | None = None
    layer_num: int | None = None
    total_layers: int | None = None
    hms_errors: list[Hms] = []
    ams: list[Unit] = []


class Assignment(BaseModel):
    printer_id: int
    ams_id: int
    tray_id: int
    spoolman_spool_id: int


class Assignments(RootModel[list[Assignment]]):
    pass


class Spool(BaseModel):
    id: int
    material: str | None = None
    brand: str | None = None
    color_name: str | None = None
    rgba: str | None = None
    label_weight: int | None = None
    weight_used: float | None = None
    storage_location: str | None = None
    archived_at: str | None = None


class Spools(RootModel[list[Spool]]):
    pass


class File(BaseModel):
    id: int
    filename: str
    print_name: str | None = None
    file_type: str | None = None
    print_time_seconds: int | None = None
    filament_used_grams: float | None = None
    sliced_for_model: str | None = None
    print_count: int = 0
    created_at: str = ""


class Files(RootModel[list[File]]):
    pass


class Filament(BaseModel):
    slot_id: int
    type: str | None = None
    color: str | None = None
    used_grams: float | None = None


class Requirements(BaseModel):
    filaments: list[Filament] = []


class QueueItem(BaseModel):
    id: int
    position: int | None = None


class Upload(BaseModel):
    id: int
    duplicate_of: int | None = None


M = TypeVar("M", bound=BaseModel)


def parsed(model: type[M], body: object) -> M:
    """Raises BambuddyFailed(`not_bambuddy`) when `body` is not that shape."""
    try:
        return model.model_validate(body)
    except ValidationError as e:
        raise BambuddyFailed("not_bambuddy") from e
