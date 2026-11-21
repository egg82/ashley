"""A fake Bambuddy behind `httpx2.MockTransport`, answering the routes she reads in the shapes its OpenAPI document
(v1.3.1) gives them: `PrinterResponse`, `PrinterStatus` with `AMSUnit`/`AMSTray`/`HMSErrorResponse`, `FileListResponse`,
`SpoolmanSlotAssignmentEnriched`, and, where the document gives no schema (the spoolman inventory spools, a file's filament
requirements), the shape its descriptions name. No live response was captured. Printer names, serials and hosts are made up.
Every request is recorded with its path, query and `X-API-Key` header; one without the key is 401.

The two writes follow the document too: `POST /api/v1/queue/` takes `PrintQueueItemCreate` (a body naming a field the
schema lacks, or a field of the wrong type, is 422) and answers a `PrintQueueItemResponse`; `POST /api/v1/library/files`
takes the multipart `file` of `Body_upload_file_api_v1_library_files_post` and answers a `FileUploadResponse`, `duplicate_of`
naming the earlier file when the same bytes came before. The document does not say which files the queue turns away, nor
which types an upload does; the fake turns away a file in `unsliced` (422) and an upload whose name ends `.exe` (415)."""

import json
import re
from dataclasses import dataclass, field

import httpx2
from ashley.bambuddy.client import HttpBambuddy
from ashley.connections.model import Kind
from money_support import HeldConnections

BASE = "https://prints.test"
KEY = "the-households-print-key"
KIND: Kind = "bambuddy"


def tray(id_: int, type_: str | None, color: str | None, remain: int, exists: bool = True) -> dict[str, object]:
    return {"id": id_, "tray_color": color, "tray_type": type_, "tray_sub_brands": "Sub " + str(type_), "remain": remain,
            "exists": exists, "state": 11}


def status(id_: int = 1, name: str = "Shed X1C", state: str = "RUNNING", name_of_print: str | None = "Benchy",
           humidity: int | None = 3) -> dict[str, object]:
    return {"id": id_, "name": name, "connected": True, "state": state, "current_print": name_of_print,
            "subtask_name": name_of_print, "progress": 42.0, "remaining_time": 95, "layer_num": 80, "total_layers": 190,
            "hms_errors": [{"code": "0300_0100", "attr": 1, "module": 3, "severity": 2, "actions": [],
                            "full_code": "0300_0100_0002_0001", "description": "Heatbed temperature abnormal"}],
            "ams": [{"id": 0, "humidity": humidity, "temp": 24.5, "is_ams_ht": False, "tray": [
                tray(0, "PLA", "FF0000FF", 80), tray(1, "PETG", "00FF00FF", -1), tray(2, None, "00000000", 0, False),
                tray(3, "PLA", "ffffff", 55)]}],
            "ams_exists": True, "vt_tray": [], "sdcard": True}


def printer(id_: int = 1, name: str = "Shed X1C") -> dict[str, object]:
    return {"id": id_, "name": name, "serial_number": "00M00A000000000", "ip_address": "192.0.2.10", "model": "X1C",
            "is_active": True, "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}


def spool(id_: int, material: str = "PLA", used: float = 100.0, archived: str | None = None,
          rgba: str | None = "FF0000FF", location: str | None = "Shelf 2") -> dict[str, object]:
    return {"id": id_, "material": material, "brand": "Acme", "color_name": "Red", "rgba": rgba, "label_weight": 1000,
            "core_weight": 250, "weight_used": used, "storage_location": location, "archived_at": archived,
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}


def library_file(id_: int, name: str, created: str = "2026-11-01T00:00:00") -> dict[str, object]:
    return {"id": id_, "folder_id": None, "filename": name + ".3mf", "file_type": "3mf", "file_size": 1,
            "thumbnail_path": None, "print_count": 2, "created_at": created, "print_name": name,
            "print_time_seconds": 3600, "filament_used_grams": 12.5, "sliced_for_model": "X1C"}


QUEUE_FIELDS: dict[str, tuple[type, ...]] = {
    "printer_id": (int, type(None)), "target_model": (str, type(None)), "library_file_id": (int, type(None)),
    "archive_id": (int, type(None)), "manual_start": (bool,), "ams_mapping": (list, type(None)),
    "plate_id": (int, type(None)), "require_previous_success": (bool,), "auto_off_after": (bool,),
    "skip_filament_check": (bool,), "quantity": (int,), "use_ams": (bool,)}
"""The `PrintQueueItemCreate` fields the adapter may send, each with the JSON types the schema gives it."""


def _typed(value: object, types: tuple[type, ...]) -> bool:
    """JSON-typed: a bool is not an integer."""
    return isinstance(value, types) and not (isinstance(value, bool) and bool not in types)


def bodies() -> dict[str, object]:
    return {
        "/api/v1/printers/": [printer()],
        "/api/v1/printers/1/status": status(),
        "/api/v1/spoolman/inventory/slot-assignments/all": [
            {"printer_id": 1, "printer_name": "Shed X1C", "ams_id": 0, "tray_id": 0, "spoolman_spool_id": 7,
             "ams_label": None}],
        "/api/v1/spoolman/inventory/spools": [spool(7, used=250), spool(8, "PETG", used=900),
                                              spool(9, archived="2026-10-01T00:00:00"), spool(10, used=0, rgba=None,
                                                                                              location="")],
        "/api/v1/library/files": [library_file(1, "Benchy", "2026-10-01T00:00:00"), library_file(2, "Phone stand"),
                                  library_file(3, "Benchy Boat Mk2", "2026-11-10T00:00:00")],
        "/api/v1/library/files/2": library_file(2, "Phone stand"),
        "/api/v1/library/files/2/filament-requirements": {
            "file_id": 2, "filename": "Phone stand.3mf", "filaments": [
                {"slot_id": 1, "type": "PLA", "color": "#FF0000", "used_grams": 10.5},
                {"slot_id": 2, "type": "PETG", "color": "00ff00ff", "used_grams": 2.0}]},
    }


@dataclass
class FakeBambuddy:
    """`status` answers every request with that status; `raw` with that body instead of JSON. `key` is the one key it
    accepts (401 otherwise). A path in `missing` answers 404, one in `forbidden` 403."""

    key: str = KEY
    status: int = 200
    raw: bytes | None = None
    answers: dict[str, object] = field(default_factory=bodies)
    missing: set[str] = field(default_factory=set[str])
    forbidden: set[str] = field(default_factory=set[str])
    seen: list[tuple[str, dict[str, str], str | None]] = field(default_factory=list[tuple[str, dict[str, str], str | None]])
    queued: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    uploaded: list[tuple[str, bytes]] = field(default_factory=list[tuple[str, bytes]])
    unsliced: set[int] = field(default_factory=set[int])
    refused_types: tuple[str, ...] = (".exe",)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append((request.url.raw_path.split(b"?")[0].decode(), dict(request.url.params), request.headers.get("x-api-key")))
        if self.status != 200:
            return httpx2.Response(self.status, headers={"location": "https://elsewhere.test/"})
        if request.headers.get("x-api-key") != self.key:
            return httpx2.Response(401, json={"detail": "Not authenticated"})
        if self.raw is not None:
            return httpx2.Response(200, content=self.raw, headers={"content-type": "text/html"})
        path = request.url.raw_path.split(b"?")[0].decode()
        if path in self.forbidden:
            return httpx2.Response(403, json={"detail": "missing permission"})
        if request.method == "POST":
            return self.write(path, request)
        body = self.answers.get(path)
        if body is None or path in self.missing:
            return httpx2.Response(404, json={"detail": "Not Found"})
        return httpx2.Response(200, content=json.dumps(body).encode(), headers={"content-type": "application/json"})

    def write(self, path: str, request: httpx2.Request) -> httpx2.Response:
        if path == "/api/v1/queue/":
            return self.enqueue(request)
        if path == "/api/v1/library/files":
            return self.add_file(request)
        return httpx2.Response(404, json={"detail": "Not Found"})

    def enqueue(self, request: httpx2.Request) -> httpx2.Response:
        sent = json.loads(request.content)
        wrong = [k for k, v in sent.items() if k not in QUEUE_FIELDS or not _typed(v, QUEUE_FIELDS[k])]
        mapping: list[object] = sent.get("ams_mapping") or []
        if wrong or any(not _typed(n, (int,)) for n in mapping):
            return httpx2.Response(422, json={"detail": [{"loc": ["body", *wrong], "msg": "invalid"}]})
        file, printer = sent.get("library_file_id"), sent.get("printer_id")
        if f"/api/v1/library/files/{file}" not in self.answers or f"/api/v1/printers/{printer}/status" not in self.answers:
            return httpx2.Response(404, json={"detail": "Not Found"})
        if file in self.unsliced:
            return httpx2.Response(422, json={"detail": "Only sliced files can be queued"})
        self.queued.append(sent)
        return httpx2.Response(200, json={**sent, "id": 100 + len(self.queued), "position": len(self.queued),
                                          "status": "pending", "waiting_reason": None, "created_at": "2026-11-20T00:00:00"})

    def add_file(self, request: httpx2.Request) -> httpx2.Response:
        named = re.search(rb'filename="([^"]+)"', request.content)
        assert named is not None and b'name="file"' in request.content, "the upload is the multipart field `file`"
        name = named.group(1).decode()
        if name.lower().endswith(self.refused_types):
            return httpx2.Response(415, json={"detail": "Unsupported file type"})
        data = request.content.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
        earlier = next((i for i, (_, d) in enumerate(self.uploaded) if d == data), None)
        self.uploaded.append((name, data))
        return httpx2.Response(200, json={
            "id": 500 + len(self.uploaded), "filename": name, "file_type": name.rsplit(".", 1)[-1].lower(),
            "file_size": len(data), "thumbnail_path": None, "metadata": None,
            "duplicate_of": None if earlier is None else 501 + earlier})

    def client(self) -> HttpBambuddy:
        return HttpBambuddy(httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle), follow_redirects=False), 5, 5)


def held(household: int) -> HeldConnections:
    found = HeldConnections()
    found.connect(household, BASE, KEY, KIND)
    return found
