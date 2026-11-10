"""The print check `ashley_cad.show` runs on each printed part alone, as it is printed: in the orientation it was modelled
in, on its own bed at its own lowest Z, so parts shown assembled (a lid on its box) never stand on one another.
Thresholds come from the run's `print.json` (`settings`), never from here.

An overhang is a triangle facing down more steeply than `overhang_deg` from vertical (0 is a wall, 90 a flat ceiling)
whose lowest point is above the bed by more than `layer_height_mm`. Overhang triangles that share an edge are one
island. From points spread over each island (about `sample_mm` apart) a ray is cast straight down to the first surface
of the same part facing up, or to its bed: that distance is the gap. An island whose smallest gap is under
`min_open_gap_mm` fails `print_gap:<part>` (it fuses or prints solid); one whose median gap, by area, is under
`min_support_gap_mm` fails `print_trapped_support:<part>` (the support under it cannot come out). Support area and bed
contact are reported as information, never as a verdict."""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

NUMBERS = ("overhang_deg", "layer_height_mm", "min_open_gap_mm", "min_support_gap_mm", "sample_mm",
           "max_print_triangles", "max_islands")
WELD_MM = 1e-4
"""Vertices this close are one when finding which overhang triangles share an edge."""
BED_MM = 1e-3
"""A down-facing triangle wholly this close to the bed lies on it."""
MAX_PAIRS = 4_000_000
"""Point-triangle pairs tested at once, which bounds the arrays a ray cast builds."""
ROUND = 3


def settings_of(raw: Any) -> dict[str, Any]:
    """The print settings in `print.json`, checked: every key of `NUMBERS` a positive number, `bed_mm` null or three
    positive numbers, `roles` a list of names. Raises ValueError naming what is wrong."""
    if not isinstance(raw, dict):
        raise ValueError("print.json is not an object")
    bad = [k for k in NUMBERS if isinstance(raw.get(k), bool) or not isinstance(raw.get(k), (int, float)) or not raw[k] > 0]
    bed = raw.get("bed_mm")
    if bed is not None and (not isinstance(bed, list) or len(bed) != 3
                            or not all(isinstance(v, (int, float)) and v > 0 for v in bed)):
        bad.append("bed_mm")
    roles = raw.get("roles")
    if not isinstance(roles, list) or not roles or not all(isinstance(r, str) and r for r in roles):
        bad.append("roles")
    if bad:
        raise ValueError(f"print.json: {bad} missing or not valid")
    return raw


def facing(tris: Any) -> tuple[Any, Any]:
    """Each triangle's unit normal (from its winding, outward in the STL `show` writes) and its area."""
    cross = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    length = np.linalg.norm(cross, axis=1)
    return cross / np.where(length > 0, length, 1.0)[:, None], length / 2


def islands(tris: Any) -> Any:
    """A label per triangle: triangles that share an edge, directly or through others, share a label."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    _, vertex = np.unique(np.round(tris.reshape(-1, 3) / WELD_MM).astype(np.int64), axis=0, return_inverse=True)
    vertex = vertex.reshape(-1, 3)
    edges = np.sort(np.stack([vertex[:, [0, 1]], vertex[:, [1, 2]], vertex[:, [2, 0]]], axis=1).reshape(-1, 2), axis=1)
    _, edge = np.unique(edges, axis=0, return_inverse=True)
    n = len(tris)
    owner = np.repeat(np.arange(n), 3)
    links = coo_matrix((np.ones(len(owner)), (owner, n + edge.reshape(-1))), shape=(n + edge.max() + 1,) * 2)
    return connected_components(links, directed=False)[1][:n]


def samples(tri: Any, spacing: float) -> Any:
    """Points strictly inside the triangle about `spacing` apart: the centroids of its split into n² equal triangles."""
    n = max(1, math.ceil(max(np.linalg.norm(tri[i] - tri[i - 1]) for i in range(3)) / spacing))
    i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    keep = i + j < n
    up = np.stack([(i[keep] + 1 / 3) / n, (j[keep] + 1 / 3) / n], axis=1)
    keep = i + j < n - 1
    down = np.stack([(i[keep] + 2 / 3) / n, (j[keep] + 2 / 3) / n], axis=1)
    uv = np.concatenate([up, down])
    return tri[0] + uv[:, :1] * (tri[1] - tri[0]) + uv[:, 1:] * (tri[2] - tri[0])


class Floor:
    """The surfaces a downward ray can land on: a part's triangles facing up, and the bed under them."""

    def __init__(self, tris: Any, bed_z: float) -> None:
        normals, areas = facing(tris)
        self.tris = tris[(normals[:, 2] > 0) & (areas * normals[:, 2] > 1e-12)]
        self.bed_z = bed_z
        self.low = self.tris.min(axis=1)
        self.high = self.tris.max(axis=1)

    def gaps(self, tri: Any, points: Any) -> Any:
        """The distance straight down from each of `points` (on `tri`) to the floor."""
        near = ((self.low[:, 0] <= tri[:, 0].max()) & (self.high[:, 0] >= tri[:, 0].min())
                & (self.low[:, 1] <= tri[:, 1].max()) & (self.high[:, 1] >= tri[:, 1].min())
                & (self.low[:, 2] <= tri[:, 2].max()))
        below = np.full(len(points), self.bed_z)
        if not near.any():
            return points[:, 2] - below
        cand = self.tris[near]
        step = max(1, MAX_PAIRS // len(cand))
        for start in range(0, len(points), step):
            chunk = points[start:start + step]
            below[start:start + step] = np.maximum(below[start:start + step], self._highest_under(cand, chunk))
        return points[:, 2] - below

    def _highest_under(self, cand: Any, points: Any) -> Any:
        """For each point, the highest Z of a candidate triangle straight under it (at or below the point), or -inf."""
        a, b, c = cand[:, 0], cand[:, 1], cand[:, 2]
        px, py = points[:, 0:1], points[:, 1:2]
        area = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1])
        wa = ((b[:, 0] - px) * (c[:, 1] - py) - (c[:, 0] - px) * (b[:, 1] - py)) / area
        wb = ((c[:, 0] - px) * (a[:, 1] - py) - (a[:, 0] - px) * (c[:, 1] - py)) / area
        wc = 1.0 - wa - wb
        z = wa * a[:, 2] + wb * b[:, 2] + wc * c[:, 2]
        hit = (wa >= -1e-9) & (wb >= -1e-9) & (wc >= -1e-9) & (z <= points[:, 2:3] + 1e-6)
        return np.where(hit, z, -np.inf).max(axis=1)


def _weighted_median(values: Any, weights: Any) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(weights[order])
    return float(values[order][np.searchsorted(cumulative, cumulative[-1] / 2)])


def _island(tris: Any, normals: Any, areas: Any, floor: Floor, spacing: float) -> dict[str, Any]:
    gaps, weights = [], []
    for tri, area in zip(tris, areas):
        points = samples(tri, spacing)
        gaps.append(floor.gaps(tri, points))
        weights.append(np.full(len(points), area / len(points)))
    gap, weight = np.concatenate(gaps), np.concatenate(weights)
    corners = tris.reshape(-1, 3)
    return {"bbox": {"min": np.round(corners.min(axis=0), ROUND).tolist(), "max": np.round(corners.max(axis=0), ROUND).tolist()},
            "area_mm2": round(float((areas * -normals[:, 2]).sum()), ROUND),
            "min_gap_mm": round(float(gap.min()), ROUND), "median_gap_mm": round(_weighted_median(gap, weight), ROUND)}


def _fits(size: Any, bed: Sequence[float] | None) -> bool | None:
    if bed is None:
        return None
    flat = (size[0] <= bed[0] and size[1] <= bed[1]) or (size[0] <= bed[1] and size[1] <= bed[0])
    return bool(flat and size[2] <= bed[2])


def part(name: str, tris: Any, settings: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """What the print check finds on one printed part, on its own bed: its report entry and the checks it fails."""
    floor = Floor(tris, float(tris[:, :, 2].min()))
    normals, areas = facing(tris)
    steep = math.sin(math.radians(settings["overhang_deg"]))
    over = (normals[:, 2] < -steep) & (tris[:, :, 2].min(axis=1) > floor.bed_z + settings["layer_height_mm"])
    on_bed = (normals[:, 2] < 0) & (tris[:, :, 2].max(axis=1) <= floor.bed_z + BED_MM)
    found: list[dict[str, Any]] = []
    if over.any():
        labels = islands(tris[over])
        for label in np.unique(labels):
            mine = labels == label
            found.append(_island(tris[over][mine], normals[over][mine], areas[over][mine], floor, settings["sample_mm"]))
    found.sort(key=lambda island: island["min_gap_mm"])
    size = tris.reshape(-1, 3).max(axis=0) - tris.reshape(-1, 3).min(axis=0)
    entry = {"name": name, "bed_z": round(floor.bed_z, ROUND), "support_area_mm2": round(float((areas[over] * -normals[over, 2]).sum()), ROUND),
             "bed_contact_mm2": round(float(areas[on_bed].sum()), ROUND), "fits_bed": _fits(size, settings.get("bed_mm")),
             "islands": found[:int(settings["max_islands"])], "islands_total": len(found)}
    checks = []
    if found and found[0]["min_gap_mm"] < settings["min_open_gap_mm"]:
        checks.append(_failed(f"print_gap:{name}", found[0]["min_gap_mm"], settings["min_open_gap_mm"]))
    median = min((island["median_gap_mm"] for island in found), default=math.inf)
    if median < settings["min_support_gap_mm"]:
        checks.append(_failed(f"print_trapped_support:{name}", median, settings["min_support_gap_mm"]))
    return entry, checks


def _failed(name: str, gap: float, needed: float) -> dict[str, Any]:
    return {"name": name, "actual": gap, "op": ">=", "target": float(needed), "tolerance": 0.0, "rests_on": []}


def check(parts: Sequence[tuple[str, Any]], settings: dict[str, Any] | None, triangles: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The report's `print` section and the failed checks, for the printed `parts` (name, triangles of shape (n, 3, 3))
    of a model of `triangles` triangles. Skipped, with the reason as a code, when there are no settings, the model is
    over `max_print_triangles` or nothing is printed; bed fit is skipped (`no_bed`) when the settings give no bed."""
    if settings is None:
        return {"skipped": "no_settings"}, []
    if triangles > settings["max_print_triangles"]:
        return {"skipped": "too_many_triangles", "triangles": triangles, "max_triangles": int(settings["max_print_triangles"])}, []
    if not parts:
        return {"skipped": "no_printed_parts"}, []
    entries, checks = [], []
    for name, tris in parts:
        entry, failed = part(name, tris, settings)
        entries.append(entry)
        checks.extend(failed)
    return {"bed_fit_skipped": None if settings.get("bed_mm") else "no_bed", "parts": entries}, checks
