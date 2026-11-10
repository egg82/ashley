"""What a model run reports (`decisions.md`, "A model is checked against them by the numbers"): the `out/report.json` a
build123d script's `ashley_cad.show` writes, understood (its parts with their roles, its checks, overlaps and the print
check's `print` section), and the verdict of each check computed here from its numbers and the source of the
measurements it rests on. The script records what it measured; it never says pass or fail."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ..runs.model import Output
from .automation_config import object_of
from .measurements import confirmed, items_of
from .measurements_file import NAME as MEASUREMENTS

REPORT = "out/report.json"
OPS = ("==", "<=", ">=", "<", ">")
Verdict = Literal["pass", "fail", "unconfirmed"]
PrintSkipped = Literal["no_settings", "too_many_triangles", "no_printed_parts"]
PRINT_SKIPPED: tuple[PrintSkipped, ...] = ("no_settings", "too_many_triangles", "no_printed_parts")
UNKNOWN_ROLE = "unknown"


@dataclass(frozen=True)
class Part:
    """One part's `volume` (mm³) and bounding box corners (mm), and its `role`: one of `print.json`'s roles as the script
    gave it, or `unknown` when it gave none. `form` is the choice row a `reference` part names as what kind of thing it
    stands in for; None on every other part."""

    name: str
    volume: float
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    role: str = UNKNOWN_ROLE
    form: str | None = None


@dataclass(frozen=True)
class Island:
    """Overhang triangles of a part that share edges: the corners of their box (mm), the area support under them covers
    on the bed (mm²), and the gap straight down from them to the part below or the bed, smallest and median by area (mm)."""

    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    area_mm2: float
    min_gap_mm: float
    median_gap_mm: float


@dataclass(frozen=True)
class PrintPart:
    """What the print check found on one printed part, checked alone on its own bed at its lowest Z (`bed_z`, mm): the bed
    area support covers (`support_area_mm2`), the area lying on the bed (`bed_contact_mm2`), whether it fits the bed
    (None when no bed is known), and its overhang `islands`, the worst gap first, of `islands_total`."""

    name: str
    bed_z: float
    support_area_mm2: float
    bed_contact_mm2: float
    fits_bed: bool | None
    islands: tuple[Island, ...]
    islands_total: int


@dataclass(frozen=True)
class PrintCheck:
    """The report's `print` section. `skip_reason` says why nothing was checked (`printed` is then empty): no print settings,
    a model over `max_triangles`, or no part that prints. `bed_fit_skipped` is `no_bed` when no bed size is known. Its
    failures are ordinary checks, `print_gap:<part>` and `print_trapped_support:<part>`."""

    skip_reason: PrintSkipped | None
    printed: tuple[PrintPart, ...] = ()
    bed_fit_skipped: Literal["no_bed"] | None = None
    max_triangles: int | None = None


@dataclass(frozen=True)
class Check:
    """A comparison of `actual` (measured on the geometry) to `target` by `op`, within `tolerance`, resting on the
    measurements `rests_on`. `verdict`: `pass`, `fail`, or `unconfirmed` when it would pass but a measurement it rests
    on is `guessed` or not in the run's measurements; every other source (`measured`, `datasheet`, `accepted`, `bound`)
    confirms."""

    name: str
    actual: float
    op: str
    target: float
    tolerance: float
    rests_on: tuple[str, ...]
    verdict: Verdict


@dataclass(frozen=True)
class Overlap:
    """Two shown parts `a` and `b` that occupy the same space: the `volume_mm3` they share and the corners of the box
    around that shared space (mm)."""

    a: str
    b: str
    volume_mm3: float
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]


@dataclass(frozen=True)
class ModelReport:
    """`overlaps` are the pairs of shown parts that share space, found among the first parts shown; `overlap_parts_skipped`
    counts the parts left out of that comparison."""

    unit: str
    parts: tuple[Part, ...]
    triangles: int
    checks: tuple[Check, ...]
    overlaps: tuple[Overlap, ...] = ()
    overlap_parts_skipped: int = 0
    print: PrintCheck | None = None
    """None for a report written before the helper had a print check."""


def holds(actual: float, op: str, target: float, tolerance: float) -> bool:
    """Whether `actual op target` holds with `tolerance` of slack in the direction that favours it: `==` is within
    ±tolerance, `<=` and `<` are bounded by target + tolerance, `>=` and `>` by target - tolerance."""
    if op == "==":
        return abs(actual - target) <= tolerance
    if op == "<=":
        return actual <= target + tolerance
    if op == ">=":
        return actual >= target - tolerance
    if op == "<":
        return actual < target + tolerance
    return actual > target - tolerance


def report_of(output: Output, inputs: Mapping[str, str]) -> ModelReport | None:
    """The report a run that ran to its end with exit 0 left in `out/report.json`, its checks judged against the
    measurements the run started with (`inputs["measurements.json"]`). None when there is no such run or file, or the
    file is not of the shape `ashley_cad.show` writes."""
    text = output.files.get(REPORT)
    if output.outcome != "ran" or output.exit_code != 0 or text is None:
        return None
    try:
        raw = object_of(json.loads(text))
    except ValueError:
        return None
    return None if raw is None else _report(raw, _confirmed(inputs))


def _confirmed(inputs: Mapping[str, str]) -> frozenset[str]:
    """The names of the run's measurements that are confirmed."""
    return frozenset(m.name for m in items_of(inputs.get(MEASUREMENTS, "")) or () if confirmed(m))


def _report(raw: dict[str, object], sure: frozenset[str]) -> ModelReport | None:
    parts, checks, triangles = _list(raw.get("parts")), _list(raw.get("checks")), raw.get("triangles")
    if raw.get("unit") != "mm" or parts is None or checks is None or type(triangles) is not int or triangles < 0:
        return None
    overlaps, skipped = _list(raw.get("overlaps", [])), raw.get("overlap_parts_skipped", 0)
    if overlaps is None or type(skipped) is not int or skipped < 0:
        return None
    made_parts = [_part(p) for p in parts]
    made_checks = [_check(c, sure) for c in checks]
    made_overlaps = [_overlap(o) for o in overlaps]
    good_parts = [p for p in made_parts if p is not None]
    good_checks = [c for c in made_checks if c is not None]
    good_overlaps = [o for o in made_overlaps if o is not None]
    if len(good_parts) != len(parts) or len(good_checks) != len(checks) or len(good_overlaps) != len(overlaps):
        return None
    printing = None if "print" not in raw else _print(raw["print"])
    if printing is False:
        return None
    return ModelReport("mm", tuple(good_parts), triangles, tuple(good_checks), tuple(good_overlaps), skipped, printing)


def _list(value: object) -> list[object] | None:
    loose: Any = value
    return list[object](loose) if isinstance(value, list) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _corner(value: object) -> tuple[float, float, float] | None:
    found = _list(value)
    if found is None or len(found) != 3:
        return None
    x, y, z = (_number(v) for v in found)
    return None if x is None or y is None or z is None else (x, y, z)


def _part(raw: object) -> Part | None:
    fields = object_of(raw)
    box = None if fields is None else object_of(fields.get("bbox"))
    if fields is None or box is None:
        return None
    name, volume, low, high = fields.get("name"), _number(fields.get("volume")), _corner(box.get("min")), _corner(box.get("max"))
    role, form = fields.get("role", UNKNOWN_ROLE), fields.get("form")
    if not isinstance(name, str) or volume is None or low is None or high is None or not isinstance(role, str):
        return None
    return Part(name, volume, low, high, role, form) if form is None or isinstance(form, str) else None


def _print(raw: object) -> PrintCheck | Literal[False]:
    """The `print` section, or False when it is not of the shape the helper writes."""
    fields = object_of(raw)
    if fields is None:
        return False
    skipped = fields.get("skipped")
    if skipped is not None:
        cap = fields.get("max_triangles")
        known = _skip_reason(skipped)
        if known is None or (cap is not None and (type(cap) is not int or cap < 0)):
            return False
        return PrintCheck(known, max_triangles=cap if type(cap) is int else None)
    parts, bed = _list(fields.get("parts")), fields.get("bed_fit_skipped")
    if parts is None or bed not in (None, "no_bed"):
        return False
    made = [_print_part(p) for p in parts]
    good = [p for p in made if p is not None]
    return PrintCheck(None, tuple(good), "no_bed" if bed else None) if len(good) == len(parts) else False


def _skip_reason(value: object) -> PrintSkipped | None:
    for reason in PRINT_SKIPPED:
        if reason == value:
            return reason
    return None


def _print_part(raw: object) -> PrintPart | None:
    fields = object_of(raw)
    islands = None if fields is None else _list(fields.get("islands"))
    if fields is None or islands is None:
        return None
    name, total, fits = fields.get("name"), fields.get("islands_total"), fields.get("fits_bed")
    support, contact, bed_z = (_number(fields.get(k)) for k in ("support_area_mm2", "bed_contact_mm2", "bed_z"))
    made = [_island(i) for i in islands]
    good = [i for i in made if i is not None]
    if (not isinstance(name, str) or type(total) is not int or total < len(islands) or support is None or contact is None
            or bed_z is None or (fits is not None and not isinstance(fits, bool)) or len(good) != len(islands)):
        return None
    return PrintPart(name, bed_z, support, contact, fits, tuple(good), total)


def _island(raw: object) -> Island | None:
    fields = object_of(raw)
    box = None if fields is None else object_of(fields.get("bbox"))
    if fields is None or box is None:
        return None
    low, high = _corner(box.get("min")), _corner(box.get("max"))
    area, least, median = (_number(fields.get(k)) for k in ("area_mm2", "min_gap_mm", "median_gap_mm"))
    if low is None or high is None or area is None or least is None or median is None:
        return None
    return Island(low, high, area, least, median)


def _overlap(raw: object) -> Overlap | None:
    fields = object_of(raw)
    box = None if fields is None else object_of(fields.get("bbox"))
    if fields is None or box is None:
        return None
    a, b, volume = fields.get("a"), fields.get("b"), _number(fields.get("volume_mm3"))
    low, high = _corner(box.get("min")), _corner(box.get("max"))
    if not isinstance(a, str) or not isinstance(b, str) or volume is None or low is None or high is None:
        return None
    return Overlap(a, b, volume, low, high)


def _check(raw: object, sure: frozenset[str]) -> Check | None:
    fields = object_of(raw)
    if fields is None:
        return None
    name, op, basis = fields.get("name"), fields.get("op"), _list(fields.get("rests_on"))
    actual, target, tolerance = _number(fields.get("actual")), _number(fields.get("target")), _number(fields.get("tolerance"))
    if (not isinstance(name, str) or not isinstance(op, str) or op not in OPS or actual is None or target is None
            or tolerance is None or tolerance < 0 or basis is None or not all(isinstance(n, str) for n in basis)):
        return None
    rests = tuple(str(n) for n in basis)
    unconfirmed = any(n not in sure for n in rests)
    verdict: Verdict = "fail" if not holds(actual, op, target, tolerance) else "unconfirmed" if unconfirmed else "pass"
    return Check(name, actual, op, target, tolerance, rests, verdict)
