"""The weak-points study `ashley_cad.show` runs for each `study(...)` a script declares: a linear static finite-element
analysis of one printed part. gmsh meshes the part's STEP into second-order tetrahedra, `ashley_fem` solves it, and the
result is a `fea` section of the report and `out/stress_<part>.glb`, the part's surface coloured by von Mises stress.

A study names the part, a material of `materials.json`, the faces held fixed and the forces on faces, all by the
build123d faces of the part's own shape. Print layers stack along Z (the orientation the print check uses), and prints
are weaker across layers than along them, so the one isotropic material is solved with the along-layer stiffness and its
safety factor is taken against the across-layer yield, less its stated tolerance: conservative for a load along any
axis. A study that cannot be answered is reported with a `skip_reason` and no numbers; it is never a stress of zero."""

import json
import math
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

import ashley_fem

MATERIALS = Path(__file__).with_name("materials.json")
MAX_NODES = 10000
"""Mesh nodes a study may solve (`study`'s `max_nodes` lowers it): measured to solve inside the sandbox's memory and time."""
BUDGET_S = 40.0
"""Seconds from the start of a study after which a mesh is not solved."""
MATCH = 1e-3
"""Relative size of a centre or area difference that still names the same face."""
ROUND = 4
TETRAHEDRON, TRIANGLE6 = 11, 9
STOPS = ((0.0, (0.19, 0.30, 0.78)), (0.25, (0.10, 0.70, 0.85)), (0.5, (0.35, 0.80, 0.30)), (0.75, (0.97, 0.80, 0.15)),
         (1.0, (0.85, 0.15, 0.12)))
"""Blue (unstressed) through green to red (the peak)."""
SKIPS = ("unknown_material", "face_not_found", "mesh_failed", "too_large", "over_time", "not_solved")


@dataclass(frozen=True)
class Study:
    part: str
    material: str
    fixed: dict[str, Any]
    loads: dict[str, tuple[Any, tuple[float, float, float]]]
    mesh_mm: float | None
    min_safety_factor: float
    max_nodes: int


class Skip(Exception):
    """A study that has no answer, with `reason` one of `SKIPS`."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason, self.detail = reason, detail


def materials() -> dict[str, Any]:
    return json.loads(MATERIALS.read_text(encoding="utf-8"))["materials"]


def _mesh(shape: Any, size: float | None, faces: dict[str, Any], max_nodes: int) -> dict[str, Any]:
    """Mesh `shape` and find the surface of gmsh each of `faces` (name -> build123d face) is. Returns nodes (n, 3), tets
    (ne, 10), each named face's node indices and triangles (6-node, indices), and all surface triangles."""
    import build123d as bd
    import gmsh

    box = shape.bounding_box()
    thickness = 2 * shape.volume / shape.area
    diagonal = math.dist(_xyz(box.min), _xyz(box.max))
    h = size if size is not None else min(max(thickness, diagonal / 50), diagonal / 8)
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.option.setNumber("Mesh.MeshSizeMax", h)
        gmsh.option.setNumber("Mesh.MeshSizeMin", h / 4)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 8)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as scratch:
            step = Path(scratch) / "part.step"
            bd.export_step(shape, step)
            gmsh.model.add("part")
            gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        surfaces = {}
        for name, face in faces.items():
            surfaces[name] = _surface_of(face, diagonal)
        try:
            gmsh.model.mesh.generate(3)
            gmsh.model.mesh.setOrder(2)
        except Exception as e:
            raise Skip("mesh_failed", f"gmsh could not mesh the part: {e}") from e
        tags, coords, _ = gmsh.model.mesh.getNodes()
        if len(tags) > max_nodes:
            raise Skip("too_large", f"the mesh at {h:.2f} mm has {len(tags)} nodes, over the {max_nodes} a study may solve; "
                                    "give a larger mesh_mm or study a smaller part")
        index = np.full(int(tags.max()) + 1, -1)
        index[tags] = np.arange(len(tags))
        _, _, tet_nodes = gmsh.model.mesh.getElements(3)
        if not len(tet_nodes) or not len(tet_nodes[0]):
            raise Skip("mesh_failed", "gmsh made no tetrahedra")
        tets = index[tet_nodes[0].astype(int)].reshape(-1, 10)
        named = {name: _face_mesh(tag, index) for name, tag in surfaces.items()}
        surface = index[gmsh.model.mesh.getElementsByType(TRIANGLE6)[1].astype(int)].reshape(-1, 6)
        return {"nodes": coords.reshape(-1, 3), "tets": tets, "faces": named, "surface": surface, "size": h, "thickness": thickness}
    finally:
        gmsh.finalize()


def _xyz(v: Any) -> tuple[float, float, float]:
    return (v.X, v.Y, v.Z)


def _surface_of(face: Any, diagonal: float) -> int:
    """The gmsh surface whose area and centre are `face`'s."""
    import gmsh

    centre = np.array(_xyz(face.center()))
    best = None
    for _, tag in gmsh.model.getEntities(2):
        area = gmsh.model.occ.getMass(2, tag)
        there = np.array(gmsh.model.occ.getCenterOfMass(2, tag))
        gap = float(np.linalg.norm(there - centre))
        if abs(area - face.area) <= MATCH * max(area, face.area) and gap <= MATCH * diagonal and (best is None or gap < best[0]):
            best = (gap, tag)
    if best is None:
        raise Skip("face_not_found", "a face named in the study is not a face of the part it names; take faces from that "
                                     "part's own shape")
    return best[1]


def _face_mesh(tag: int, index: Any) -> dict[str, Any]:
    import gmsh

    nodes, _ = gmsh.model.mesh.getNodes(2, tag, includeBoundary=True)[:2]
    triangles = gmsh.model.mesh.getElementsByType(TRIANGLE6, tag)[1]
    return {"nodes": index[nodes.astype(int)], "triangles": index[triangles.astype(int)].reshape(-1, 6)}


def _forces(mesh: dict[str, Any], loads: dict[str, tuple[Any, tuple[float, float, float]]]) -> Any:
    """Nodal forces (n, 3) for each load spread over its face the way quadratic triangles carry a uniform traction:
    nothing on a corner, a third of the triangle's area on each edge midpoint."""
    nodes = mesh["nodes"]
    forces = np.zeros((len(nodes), 3))
    for name, (_, vector) in loads.items():
        tris = mesh["faces"][name]["triangles"]
        corners = nodes[tris[:, :3]]
        area = np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1) / 2
        weight = np.zeros(len(nodes))
        np.add.at(weight, tris[:, 3:].reshape(-1), np.repeat(area / 3, 3))
        forces += weight[:, None] / weight.sum() * np.array(vector)
    return forces


def _where(point: Any, mesh: dict[str, Any]) -> dict[str, Any]:
    """The named face the point is nearest to and how far from it (0 on it), among the fixed and loaded faces."""
    nodes = mesh["nodes"]
    best = min(((float(np.min(np.linalg.norm(nodes[f["nodes"]] - point, axis=1))), name) for name, f in mesh["faces"].items()),
               default=None)
    return {"point_mm": [round(float(v), ROUND) for v in point],
            "nearest_named_face": None if best is None else best[1],
            "distance_to_it_mm": None if best is None else round(best[0], ROUND)}


def _strength(material: dict[str, Any]) -> tuple[float, float]:
    """The across-layer yield less its tolerance and the yield itself, MPa: the low and high of the safety factor."""
    row = material["yield_across_layers_mpa"]
    return row["value"] - row["tolerance"], row["value"]


def run_one(study: Study, shape: Any) -> tuple[dict[str, Any], bytes]:
    """The `fea` entry of one study and its stress view (a GLB), or `Skip` for why there is no answer."""
    started = time.monotonic()
    found = materials().get(study.material)
    if found is None:
        raise Skip("unknown_material", f"material {study.material!r} is not in materials.json: {sorted(materials())}")
    faces = {**study.fixed, **{name: face for name, (face, _) in study.loads.items()}}
    mesh = _mesh(shape, study.mesh_mm, faces, study.max_nodes)
    meshed = time.monotonic() - started
    if meshed > BUDGET_S:
        raise Skip("over_time", f"meshing took {meshed:.0f} s, past the {BUDGET_S:.0f} s a study has")
    fixed = np.unique(np.concatenate([mesh["faces"][n]["nodes"] for n in study.fixed]))
    got = ashley_fem.solve(mesh["nodes"], mesh["tets"], found["youngs_modulus_mpa"]["value"], found["poisson_ratio"]["value"],
                           fixed, _forces(mesh, study.loads))
    if not np.isfinite(got.von_mises).all() or not got.residual <= ashley_fem.TOLERANCE:
        raise Skip("not_solved", f"the solve did not converge (residual {got.residual:.2g}, need {ashley_fem.TOLERANCE:g})")
    peak = int(np.argmax(got.von_mises))
    reach = np.linalg.norm(got.displacement, axis=1)
    low, high = _strength(found)
    stress = float(got.von_mises[peak])
    return {"part": study.part, "material": study.material, "skip_reason": None,
            "mesh": {"nodes": len(mesh["nodes"]), "elements": len(mesh["tets"]), "size_mm": round(mesh["size"], 3),
                     "mean_thickness_mm": round(mesh["thickness"], 3), "elements_through_thickness": round(mesh["thickness"] / mesh["size"], 2)},
            "seconds": round(time.monotonic() - started, 2),
            "peak_von_mises_mpa": round(stress, 3), "peak": _where(mesh["nodes"][peak], mesh),
            "max_deflection_mm": round(float(reach.max()), 5), "deflection_at_mm": [round(float(v), ROUND) for v in mesh["nodes"][int(np.argmax(reach))]],
            "safety_factor": {"low": round(low / stress, 3), "high": round(high / stress, 3)},
            "min_safety_factor": study.min_safety_factor,
            "basis": {"strength_across_layers_mpa": [low, high], "layer_axis": "Z", "material_source": found["source"],
                      "assumed": [k for k, row in found.items() if isinstance(row, dict) and row.get("assumed")],
                      "note": "isotropic solve with the along-layer stiffness; the safety factor is against the across-layer yield "
                              "less its tolerance (low) and at it (high), because prints are weaker across layers than along them. "
                              "A peak at a fixed edge or a load edge can be a sharp-corner artefact of the mesh."}}, \
        _stress_view(mesh, got.von_mises)


def _colour(value: float, top: float) -> tuple[float, float, float]:
    t = min(max(value / top, 0.0), 1.0) if top > 0 else 0.0
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        if t <= b:
            f = (t - a) / (b - a)
            return tuple(ca[i] + f * (cb[i] - ca[i]) for i in range(3))  # type: ignore[return-value]
    return STOPS[-1][1]


def _stress_view(mesh: dict[str, Any], stress: Any) -> bytes:
    """A GLB (metres, Y-up, as `ashley_cad`'s) of the part's surface, each vertex coloured by its von Mises stress against
    the peak."""
    nodes = mesh["nodes"]
    tris = mesh["surface"]
    sub = np.concatenate([tris[:, [0, 3, 5]], tris[:, [3, 1, 4]], tris[:, [5, 4, 2]], tris[:, [3, 4, 5]]])
    used, inverse = np.unique(sub, return_inverse=True)
    metres = nodes[used] / 1000.0
    positions = np.stack([metres[:, 0], metres[:, 2], -metres[:, 1]], axis=1).astype("<f4")
    top = float(stress.max())
    colours = np.array([_colour(float(v), top) for v in stress[used]], dtype="<f4")
    indices = inverse.reshape(-1, 3).astype("<u4")
    blobs = [positions.tobytes(), colours.tobytes(), indices.tobytes()]
    body = b"".join(b + b"\0" * (-len(b) % 4) for b in blobs)
    offsets = [0, len(blobs[0]) + (-len(blobs[0]) % 4)]
    offsets.append(offsets[1] + len(blobs[1]) + (-len(blobs[1]) % 4))
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
           "materials": [{"doubleSided": True, "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.8}}],
           "meshes": [{"name": "stress", "primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2, "material": 0, "mode": 4}]}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3",
                          "min": positions.min(axis=0).tolist(), "max": positions.max(axis=0).tolist()},
                         {"bufferView": 1, "componentType": 5126, "count": len(colours), "type": "VEC3"},
                         {"bufferView": 2, "componentType": 5125, "count": indices.size, "type": "SCALAR"}],
           "bufferViews": [{"buffer": 0, "byteOffset": offsets[0], "byteLength": len(blobs[0]), "target": 34962},
                           {"buffer": 0, "byteOffset": offsets[1], "byteLength": len(blobs[1]), "target": 34962},
                           {"buffer": 0, "byteOffset": offsets[2], "byteLength": len(blobs[2]), "target": 34963}],
           "buffers": [{"byteLength": len(body)}]}
    head = json.dumps(doc, separators=(",", ":")).encode()
    head += b" " * (-len(head) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(head) + 8 + len(body)) + struct.pack("<I4s", len(head), b"JSON") + head
            + struct.pack("<I4s", len(body), b"BIN\0") + body)


def run(studies: list[Study], shapes: dict[str, Any], out: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The report's `fea` section for the declared studies: one entry each in order, a skipped one carrying
    `skip_reason` and `detail`. Writes `stress_<part>.glb` into `out` for each study that was solved (a part studied twice
    keeps the last). Each solved study also gives a check `fea_safety_factor:<part>`: the low safety factor against its
    `min_safety_factor`; the app judges it as any other."""
    entries, checks = [], []
    for study in studies:
        try:
            entry, view = run_one(study, shapes[study.part])
            (out / f"stress_{study.part}.glb").write_bytes(view)
            entry["view"] = f"stress_{study.part}.glb"
            entries.append(entry)
            checks.append({"name": f"fea_safety_factor:{study.part}", "actual": entry["safety_factor"]["low"], "op": ">=",
                           "target": study.min_safety_factor, "tolerance": 0.0, "rests_on": []})
        except Skip as e:
            entries.append({"part": study.part, "material": study.material, "skip_reason": e.reason, "detail": e.detail})
    return {"studies": entries}, checks
