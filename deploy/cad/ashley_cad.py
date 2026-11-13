"""What a build123d model script ends with, in the CAD image (deploy/cad/Containerfile). The script runs in `/work`
with the bench's facts as `facts.json` (or `measurements.json`, which an app not yet updated writes); `show` writes
`out/model.glb`, `out/model.stl`, `out/model.3mf` and `out/report.json` beside it, all in millimetres (GLB is metres
and Y-up, as glTF says; the viewer turns it back).

    from ashley_cad import check, measured, show
    width = measured("board_width")
    box = Box(width + 4, 30, 10)
    check("clearance", 2.0, ">=", 1.5, rests_on=["board_width"])
    show(box)

A part can say what it is for, from the closed list in `print.json`'s `roles`: `show(("lid", lid, "enclosure"))`. A
part with no role is `unknown`. A `reference` part is the real object modelled for fit, and names the choice row that
says what kind of thing it is: `show(("strap", s, "reference", "lanyard_form"))`. It is checked for overlaps, every
`parts_apart` check against it rests on that row, and it is left out of the print check, which runs on every other part
(`ashley_print`). A choice row's value is `chosen(name)`, which a script may compare to one of the row's own options.

An existing model on the bench (an uploaded STL, 3MF or STEP file piece) is `existing(piece_id)`, a shape to change:

    holder = existing(7)
    show(joined(holder, clip))

`check` records a comparison of a number the script measured on its geometry; the app judges it from the numbers and
the measurement's source, so nothing here says pass or fail."""

import io
import itertools
import json
import math
import re
import struct
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Deflections for all three meshes. One pair keeps the triangles the same in every file.
LINEAR_MM = 0.02
ANGULAR_RAD = 0.2
OPS = ("==", "<=", ">=", "<", ">")
MAX_OVERLAP_PARTS = 8
"""Parts `show` compares in pairs; the rest are counted in the report as skipped."""

INPUTS = Path("inputs.json")
PRINT = Path("print.json")
UNKNOWN = "unknown"
REFERENCE = "reference"
CHOICE = "choice"
ROUNDING = 5
MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
"""Millimetres in each unit an STL's numbers can be in (the file does not say)."""
MODEL_UNITS = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}
"""Millimetres in each unit a 3MF model declares."""
"""Decimals of a millimetre two STL vertices still count as one at; binary STL stores float32, which is finer."""

FACTS = Path("facts.json")
LEGACY_FACTS = Path("measurements.json")
_rows: dict[str, dict[str, Any]] | None = None
_read: list[str] = []
_checks: list[dict[str, Any]] = []


def _file() -> Path | None:
    """The run's facts file: `facts.json`, or the older `measurements.json` an app not yet updated writes."""
    return next((p for p in (FACTS, LEGACY_FACTS) if p.is_file()), None)


def _load() -> dict[str, dict[str, Any]]:
    """Every row of the run's facts by name, numbers and choices alike."""
    global _rows
    if _rows is None:
        found = _file()
        if found is None:
            raise FileNotFoundError("facts.json is not here: this bench has no facts piece")
        _rows = {item["name"]: item for item in json.loads(found.read_text(encoding="utf-8"))["items"]}
    return _rows


def _names(choices: bool) -> list[str]:
    """The names of the choice rows, or of the number rows; none when the run has no facts."""
    rows = _load() if _file() is not None else {}
    return sorted(n for n, row in rows.items() if (row.get("kind") == CHOICE) == choices)


def _remember(name: str) -> None:
    if name not in _read:
        _read.append(name)


def measured(name: str) -> float:
    """The value of measurement `name` in its unit (millimetres, degrees or a count), and remember the script
    read it, so a check that does not say what it rests on rests on every measurement read before it. A number given
    a choice (`given`) remembers that choice too."""
    row = _load().get(name)
    if row is None or row.get("kind") == CHOICE:
        hint = f"; {name!r} is a choice, read with chosen({name!r})" if row is not None else ""
        raise KeyError(f"no measurement named {name!r}; the bench has {_names(False)}{hint}")
    _remember(name)
    if "given" in row:
        _remember(row["given"])
    return float(row["value"])


def chosen(name: str) -> str:
    """The value of choice row `name` (what kind of thing something is, in plain words), remembered as `measured`
    remembers a number, so a check that does not say what it rests on rests on it too."""
    row = _load().get(name)
    if row is None or row.get("kind") != CHOICE:
        raise KeyError(f"no choice named {name!r}; the bench has the choices {_names(True)}")
    _remember(name)
    return str(row["value"])


def _mesh_triangles(data: bytes) -> Any:
    """The triangles of a binary or ASCII STL as an array of shape (n, 3, 3)."""
    import numpy as np

    if len(data) >= 84 and len(data) == 84 + 50 * struct.unpack_from("<I", data, 80)[0]:
        record = np.dtype([("normal", "<f4", 3), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
        return np.frombuffer(data, dtype=record, offset=84)["vertices"].astype(np.float64)
    rows = [line.split() for line in data.decode("utf-8", errors="replace").splitlines() if line.split()[:1] == ["vertex"]]
    if not rows or len(rows) % 3:
        raise ValueError("not an STL: neither a binary one of the size its triangle count gives nor an ASCII one")
    return np.array([[float(v) for v in row[1:4]] for row in rows]).reshape(-1, 3, 3)


def _stl_as_3mf(data: bytes, unit: str = "mm") -> bytes:
    """A 3MF holding the STL's triangles with shared vertices joined and degenerate triangles dropped, which is how a
    mesh reaches build123d's `Mesher` (its `import_stl` gives a single face with no volume, which nothing can join). The
    STL's numbers are in `unit`; the 3MF's are millimetres."""
    import numpy as np

    triangles = _mesh_triangles(data) * MM[unit]
    points, inverse = np.unique(np.round(triangles.reshape(-1, 3), ROUNDING), axis=0, return_inverse=True)
    index = inverse.reshape(-1, 3)
    index = index[(index[:, 0] != index[:, 1]) & (index[:, 1] != index[:, 2]) & (index[:, 0] != index[:, 2])]
    vertices = "".join(f'<vertex x="{x:.{ROUNDING}f}" y="{y:.{ROUNDING}f}" z="{z:.{ROUNDING}f}"/>' for x, y, z in points)
    faces = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in index)
    model = ('<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" type="model">'
             f'<mesh><vertices>{vertices}</vertices><triangles>{faces}</triangles></mesh></object></resources>'
             '<build><item objectid="1"/></build></model>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)
    return out.getvalue()


def _declared_unit(threemf: bytes) -> float:
    """Millimetres in the unit the 3MF's model declares (millimetres when it says nothing), since `Mesher` reads the
    numbers as they stand."""
    with zipfile.ZipFile(io.BytesIO(threemf)) as z:
        head = z.read("3D/3dmodel.model")[:2000].decode("utf-8", errors="replace")
    named = re.search(r'<model[^>]*\sunit="([a-z]+)"', head)
    return MODEL_UNITS[named.group(1)] if named and named.group(1) in MODEL_UNITS else 1.0


def _mesh(threemf: bytes) -> Any:
    """The solid (or compound of solids) the 3MF's meshes make, in millimetres. Fails for a mesh that does not close."""
    import build123d as bd

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as scratch:
        converted = Path(scratch) / "mesh.3mf"
        converted.write_bytes(threemf)
        shapes = bd.Mesher().read(converted)
    shape = shapes[0] if len(shapes) == 1 else bd.Compound(shapes)
    if not shape.solids() or shape.volume <= 0:
        raise ValueError("the mesh does not close into a solid (it has holes, loose faces or faces pointing inward), so nothing can be added to it or cut from it")
    factor = _declared_unit(threemf)
    return shape if factor == 1.0 else bd.scale(shape, by=factor)


def existing(piece: int, unit: str = "mm") -> Any:
    """The model of file piece `piece` on the bench (an STL, 3MF or STEP the person uploaded), as a shape in millimetres
    to change: STL and 3MF come back as solids made of the mesh's triangles, so a box or cylinder can be added to or cut
    from them and the result shown; STEP comes back as the solids it holds. STEP and 3MF files declare their unit and are converted to millimetres; an
    STL does not, so say `unit` (`mm`, `cm`, `m` or `in`) when it is not millimetres, and check the size against what
    you were told. Fails for a mesh that does not close into a solid, and, naming the pieces it has and the ones
    left out and why, for a piece that is not an input of this run."""
    import build123d as bd

    index = json.loads(INPUTS.read_text(encoding="utf-8")) if INPUTS.is_file() else {"items": [], "left_out": []}
    found = next((item for item in index["items"] if item["piece"] == piece), None)
    if found is None:
        have = {item["piece"]: item["name"] for item in index["items"]}
        out = {item["piece"]: f'{item["name"]} ({item["why"]})' for item in index["left_out"]}
        raise KeyError(f"piece {piece} is not an input of this run; the bench has {have}, and left out {out}")
    path = Path(found["file"])
    suffix = path.suffix.lower()
    if unit not in MM:
        raise ValueError(f"unit {unit!r} is not one of {sorted(MM)}")
    if unit != "mm" and suffix != ".stl":
        raise ValueError(f"{path.suffix} files declare their unit; `unit` is for an STL")
    if suffix in (".step", ".stp"):
        return bd.import_step(path)
    if suffix == ".3mf":
        return _mesh(path.read_bytes())
    return _mesh(_stl_as_3mf(path.read_bytes(), unit))


def _volume_slack(*shapes: Any) -> float:
    return 1e-6 * max(abs(shape.volume) for shape in shapes) + 1e-6


def joined(base: Any, part: Any) -> Any:
    """`base` with `part` added. A boolean on a mesh can quietly return only one of its inputs (a real STL did, with the
    box overlapping it), so the result must hold at least all of `base` and at most both; anything else fails."""
    result = base + part
    slack = _volume_slack(base, part)
    if not base.volume - slack <= result.volume <= base.volume + part.volume + slack:
        raise ValueError(f"the union lost or invented volume: base {base.volume:.1f}, part {part.volume:.1f}, result {result.volume:.1f} mm3")
    return result


def cut_away(base: Any, part: Any) -> Any:
    """`base` without `part`, checked as `joined` is: the result is no larger than `base` and loses no more than `part`."""
    result = base - part
    slack = _volume_slack(base, part)
    if not base.volume - part.volume - slack <= result.volume <= base.volume + slack:
        raise ValueError(f"the cut lost or invented volume: base {base.volume:.1f}, part {part.volume:.1f}, result {result.volume:.1f} mm3")
    return result


def check(name: str, actual: float, op: str, target: float, *, tolerance: float = 0.0,
          rests_on: Sequence[str] | None = None) -> None:
    """Record that `actual` (measured on the geometry) compares to `target` by `op` (`==`, `<=`, `>=`, `<`, `>`),
    within `tolerance`, in the same unit. `rests_on` names the facts the check depends on; left out, it is
    every measurement read so far."""
    if not name or any(c["name"] == name for c in _checks):
        raise ValueError(f"check name {name!r} is empty or already used")
    if op not in OPS:
        raise ValueError(f"check {name!r}: op {op!r} is not one of {OPS}")
    if not all(math.isfinite(v) for v in (actual, target, tolerance)) or tolerance < 0:
        raise ValueError(f"check {name!r}: actual, target and tolerance must be finite, tolerance not negative")
    basis = list(_read if rests_on is None else rests_on)
    unknown = [n for n in basis if n not in _load()] if basis else []
    if unknown:
        raise KeyError(f"check {name!r} rests on {unknown}, which the bench does not measure")
    _checks.append({"name": name, "actual": float(actual), "op": op, "target": float(target),
                    "tolerance": float(tolerance), "rests_on": basis})


def _shape(part: Any) -> Any:
    """The build123d shape of a Shape or of a builder holding one."""
    return part.part if hasattr(part, "part") else part


def _print_settings() -> dict[str, Any] | None:
    """The run's print settings, or None when it was given none."""
    import ashley_print

    return ashley_print.settings_of(json.loads(PRINT.read_text(encoding="utf-8"))) if PRINT.is_file() else None


def _named(parts: Sequence[Any], roles: Sequence[str] | None) -> list[tuple[str, Any, str]]:
    """Each part as (name, shape, role). Raises ValueError for a tuple of another length, a role not in `roles` (any
    role is taken when the run has no print settings to say which there are), or a form that is wrong (`_form`)."""
    named: list[tuple[str, Any, str]] = []
    for i, part in enumerate(parts, 1):
        if not isinstance(part, tuple):
            part = (f"part{i}", part)
        if len(part) not in (2, 3, 4):
            raise ValueError(f"part {i} is a tuple of {len(part)}; give (name, shape), (name, shape, role) or "
                             "(name, shape, \"reference\", form)")
        role = str(part[2]) if len(part) >= 3 else UNKNOWN
        if len(part) >= 3 and roles is not None and role not in roles:
            raise ValueError(f"part {part[0]!r}: role {role!r} is not one of {list(roles)}")
        _form(part, role)
        named.append((str(part[0]), _shape(part[1]), role))
    return named


def _form(part: tuple[Any, ...], role: str) -> None:
    """Raises ValueError unless a reference part names a choice row as its fourth element and no other part names one:
    a stand-in is only as right as the kind of thing it is taken to be, so that is a row with a source."""
    if role != REFERENCE:
        if len(part) == 4:
            raise ValueError(f"part {part[0]!r}: only a reference part names a form")
        return
    choices = _names(True)
    if len(part) != 4:
        raise ValueError(f"part {part[0]!r} is a reference, a stand-in for a real object: say what kind of thing it is "
                         f"with a choice row in the facts piece and name it, as (name, shape, \"reference\", "
                         f"\"<choice name>\"); the bench has the choices {choices}")
    if str(part[3]) not in choices:
        raise ValueError(f"part {part[0]!r}: form {part[3]!r} is not a choice row of the facts; the bench has "
                         f"the choices {choices}")


def _forms(parts: Sequence[Any]) -> dict[str, str]:
    """The choice row each reference part names, by part name (`_named` has checked them)."""
    return {str(p[0]): str(p[3]) for p in parts if isinstance(p, tuple) and len(p) == 4}


def _stl_triangles(path: Path) -> int:
    with path.open("rb") as f:
        return struct.unpack("<I", f.read(84)[80:84])[0]


GLTF_DTYPES = {5121: "u1", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
GLTF_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}


def _accessor_rows(doc: dict[str, Any], binary: bytes, index: int) -> Any:
    import numpy as np

    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(GLTF_DTYPES[acc["componentType"]])
    width = GLTF_WIDTHS[acc["type"]]
    stride = view.get("byteStride") or dtype.itemsize * width
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    raw = np.frombuffer(binary, dtype=np.uint8, count=stride * (acc["count"] - 1) + dtype.itemsize * width, offset=start)
    rows = np.lib.stride_tricks.as_strided(raw, shape=(acc["count"], dtype.itemsize * width), strides=(stride, 1))
    return np.ascontiguousarray(rows).view(dtype).reshape(acc["count"], width)


def _one_primitive_per_mesh(path: Path) -> None:
    """Rewrite the GLB so each mesh is one indexed primitive. OCCT writes a primitive and four accessors per face, and a
    mesh imported from an STL has a face per triangle: the JSON outweighs the geometry and a viewer makes a draw call per
    triangle. Positions and normals are kept; the texture coordinates nothing reads are dropped."""
    import numpy as np

    data = path.read_bytes()
    json_len = struct.unpack("<I", data[12:16])[0]
    doc = json.loads(data[20:20 + json_len])
    binary = data[20 + json_len + 8:]
    chunks: list[bytes] = []
    accessors: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []

    def add(rows: Any, kind: str, component: int, target: int, bounds: bool) -> int:
        blob = np.ascontiguousarray(rows).tobytes()
        offset = sum(len(c) for c in chunks)
        chunks.append(blob + b"\0" * (-len(blob) % 4))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(blob), "target": target})
        accessor: dict[str, Any] = {"bufferView": len(views) - 1, "componentType": component, "count": len(rows), "type": kind}
        if bounds:
            accessor["min"], accessor["max"] = rows.min(axis=0).tolist(), rows.max(axis=0).tolist()
        accessors.append(accessor)
        return len(accessors) - 1

    meshes = []
    for mesh in doc["meshes"]:
        positions, normals, indices, base = [], [], [], 0
        for prim in mesh["primitives"]:
            positions.append(_accessor_rows(doc, binary, prim["attributes"]["POSITION"]))
            normals.append(_accessor_rows(doc, binary, prim["attributes"]["NORMAL"]))
            indices.append(_accessor_rows(doc, binary, prim["indices"]).astype("<u4").reshape(-1) + base)
            base += len(positions[-1])
        attributes = {"POSITION": add(np.concatenate(positions), "VEC3", 5126, 34962, True),
                      "NORMAL": add(np.concatenate(normals), "VEC3", 5126, 34962, False)}
        meshes.append({"name": mesh.get("name", "model"), "primitives": [
            {"attributes": attributes, "indices": add(np.concatenate(indices), "SCALAR", 5125, 34963, False), "mode": 4}]})
    body = b"".join(chunks)
    head = json.dumps({**{k: v for k, v in doc.items() if k not in ("accessors", "bufferViews", "buffers", "meshes")},
                       "meshes": meshes, "accessors": accessors, "bufferViews": views,
                       "buffers": [{"byteLength": len(body)}]}, separators=(",", ":")).encode()
    head += b" " * (-len(head) % 4)
    total = 12 + 8 + len(head) + 8 + len(body)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(head), b"JSON") + head
                     + struct.pack("<I4s", len(body), b"BIN\0") + body)


def _part_report(name: str, shape: Any, role: str, form: str | None) -> dict[str, Any]:
    box = shape.bounding_box()
    found: dict[str, Any] = {"name": name, "role": role, "volume": float(shape.volume),
                             "bbox": {"min": [box.min.X, box.min.Y, box.min.Z], "max": [box.max.X, box.max.Y, box.max.Z]}}
    return found if form is None else {**found, "form": form}


def _boxes_meet(a: Any, b: Any) -> bool:
    """Whether the bounding boxes share volume; boxes that only touch cannot hold overlapping solids."""
    x, y = a.bounding_box(), b.bounding_box()
    return (min(x.max.X, y.max.X) - max(x.min.X, y.min.X) > 1e-6 and min(x.max.Y, y.max.Y) - max(x.min.Y, y.min.Y) > 1e-6
            and min(x.max.Z, y.max.Z) - max(x.min.Z, y.min.Z) > 1e-6)


def _overlap(a: Any, b: Any) -> tuple[float, Any] | None:
    """The volume the solids share and the shape it makes, or None when they only touch or share a sliver."""
    common = a & b
    volume = float(common.volume) if common is not None else 0.0
    return (volume, common) if volume > _volume_slack(a, b) else None


def _overlaps(named: Sequence[tuple[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for (a, shape_a), (b, shape_b) in itertools.combinations(named[:MAX_OVERLAP_PARTS], 2):
        if not _boxes_meet(shape_a, shape_b):
            continue
        shared = _overlap(shape_a, shape_b)
        if shared is not None:
            box = shared[1].bounding_box()
            found.append({"a": a, "b": b, "volume_mm3": shared[0],
                          "bbox": {"min": [box.min.X, box.min.Y, box.min.Z], "max": [box.max.X, box.max.Y, box.max.Z]}})
    return found


def _apart_checks(names: Sequence[str], overlaps: Sequence[dict[str, Any]], forms: dict[str, str]) -> list[dict[str, Any]]:
    """The volume each compared pair shares against none: for every overlapping pair, which fails, and for every pair
    with a reference part, resting on the forms its reference parts name, so a fit against a stand-in of a guessed form
    is never a plain pass."""
    shared = {(o["a"], o["b"]): o["volume_mm3"] for o in overlaps}
    found = []
    for a, b in itertools.combinations(names[:MAX_OVERLAP_PARTS], 2):
        if (a, b) in shared or a in forms or b in forms:
            rests = list(dict.fromkeys(forms[n] for n in (a, b) if n in forms))
            found.append({"name": f"parts_apart:{a}:{b}", "actual": shared.get((a, b), 0.0), "op": "==", "target": 0.0,
                          "tolerance": 0.0, "rests_on": rests})
    return found


def _printed_triangles(named: Sequence[tuple[str, Any, str]], scratch: Path) -> list[tuple[str, Any]]:
    """Each printed part's triangles, meshed as `model.stl` is."""
    import build123d as bd

    found = []
    for i, (name, shape, role) in enumerate(named):
        if role != REFERENCE:
            bd.export_stl(shape, scratch / f"{i}.stl", tolerance=LINEAR_MM, angular_tolerance=ANGULAR_RAD)
            found.append((name, _mesh_triangles((scratch / f"{i}.stl").read_bytes())))
    return found


def show(*parts: Any) -> None:
    """Mesh the parts once and write the model files and `out/report.json`. Each part is a shape, a builder holding
    one, a `(name, shape)` pair, a `(name, shape, role)` triple or a reference part's `(name, shape, "reference", form)`;
    the unnamed are `part1`, `part2`... The report carries each part's role (and a reference part's form), bounding box
    and volume, the triangle count and the checks. Parts shown together are separate objects, so any two that share volume
    (compared for the first `MAX_OVERLAP_PARTS`) are listed in `overlaps` and each adds a failed check `parts_apart:<a>:<b>`,
    which a pair with a reference part has whether they overlap or not (`_apart_checks`);
    parts meant to touch are one part, made with `joined`. The print check (`ashley_print`) adds the report's `print`
    section and its failed checks `print_gap:<part>` and `print_trapped_support:<part>`."""
    import ashley_print
    import build123d as bd  # imported late: OCP takes seconds to load and a script that fails earlier need not pay

    settings = _print_settings()
    named = _named(parts, None if settings is None else settings["roles"])
    forms = _forms(parts)
    if not named:
        raise ValueError("show() needs at least one part")
    for name, shape, _ in named:
        shape.label = name
    whole = bd.Compound([shape for _, shape, _ in named], label="model")
    out = Path("out")
    out.mkdir(exist_ok=True)
    bd.export_stl(whole, out / "model.stl", tolerance=LINEAR_MM, angular_tolerance=ANGULAR_RAD)
    mesher = bd.Mesher()
    for name, shape, _ in named:
        mesher.add_shape(shape, linear_deflection=LINEAR_MM, angular_deflection=ANGULAR_RAD, part_number=name)
    mesher.write(out / "model.3mf")
    bd.export_gltf(whole, out / "model.glb", binary=True, linear_deflection=LINEAR_MM, angular_deflection=ANGULAR_RAD)
    _one_primitive_per_mesh(out / "model.glb")
    overlaps = _overlaps([(n, s) for n, s, _ in named])
    triangles = _stl_triangles(out / "model.stl")
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as scratch:
        printed = [] if settings is None or triangles > settings["max_print_triangles"] else _printed_triangles(named, Path(scratch))
        printing, print_checks = ashley_print.check(printed, settings, triangles)
    apart = _apart_checks([n for n, _, _ in named], overlaps, forms)
    report = {"unit": "mm", "parts": [_part_report(n, s, r, forms.get(n)) for n, s, r in named], "triangles": triangles,
              "checks": _checks + apart + print_checks, "overlaps": overlaps,
              "overlap_parts_skipped": max(0, len(named) - MAX_OVERLAP_PARTS), "print": printing}
    (out / "report.json").write_text(json.dumps(report), encoding="utf-8")
