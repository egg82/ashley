"""Wire models for what a model run leaves: its stored artifacts with the links that reach them (`RunOutput.artifacts`)
and its report with a verdict for each check and what the print check found (`RunOutput.report`)."""

import time
from typing import Literal

from pydantic import BaseModel

from ..files import config as files_config
from ..files import links
from ..runs.model import Artifact
from ..workshop.model_report import Island, ModelReport, Overlap, PrintCheck, PrintPart, PrintSkipped

CONFIG = files_config.load()


class RunArtifact(BaseModel):
    """A binary file the run made and kept: its `name` in the working directory, `size_bytes` and `media_type`. `url` is
    a download link on this site, no session needed, that stops at `expires_at` (Unix seconds), so a page that stays open
    reads the bench again before then; null when this process mints no links."""

    name: str
    size_bytes: int
    media_type: str
    url: str | None
    expires_at: int | None


class ReportPart(BaseModel):
    """One part's `volume` (mm³) and the corners of its bounding box (mm, x y z). `role` is what the script said the part
    is for, one of the roles in the print settings (`reference` is the real object modelled for fit, which is never
    printed), or `unknown` when it said nothing. `form` is the measurements choice row a `reference` part names as what
    kind of thing it stands in for, null on every other part."""

    name: str
    role: str
    form: str | None
    volume: float
    bbox_min: list[float]
    bbox_max: list[float]


class ReportCheck(BaseModel):
    """A comparison the script made of a number it measured on the geometry: `actual op target` within `tolerance`, resting
    on the measurements `rests_on`. `verdict` is computed by the app: `pass`, `fail`, or `unconfirmed` when it would pass
    but a measurement it rests on is guessed or missing from the run; any other source confirms."""

    name: str
    actual: float
    op: str
    target: float
    tolerance: float
    rests_on: list[str]
    verdict: Literal["pass", "fail", "unconfirmed"]


class ReportOverlap(BaseModel):
    """Two shown parts, `a` and `b`, that occupy the same space: the `volume_mm3` they share and the corners of the box
    around it (mm, x y z). Each is also a failed `parts_apart` check."""

    a: str
    b: str
    volume_mm3: float
    bbox_min: list[float]
    bbox_max: list[float]


class ReportIsland(BaseModel):
    """Overhang faces of a part that join up: the corners of their box (mm, x y z), the bed area support under them covers
    (`area_mm2`), and the gap straight down to the part below or the bed, smallest and median by area (mm)."""

    bbox_min: list[float]
    bbox_max: list[float]
    area_mm2: float
    min_gap_mm: float
    median_gap_mm: float


class ReportPrintPart(BaseModel):
    """What the print check found on one printed part, checked alone on its own bed at its lowest Z (`bed_z`, mm): the
    bed area its support covers (`support_area_mm2`, which is
    information, never a failure), the area lying on the bed (`bed_contact_mm2`), `fits_bed` (null when no bed size is
    known), and its overhang `islands`, the smallest gap first, the first few of `islands_total`."""

    name: str
    bed_z: float
    support_area_mm2: float
    bed_contact_mm2: float
    fits_bed: bool | None
    islands: list[ReportIsland]
    islands_total: int


class ReportPrint(BaseModel):
    """The print check of the parts as modelled, flat on the bed. `skip_reason` says why nothing was checked, and `printed` is
    then empty: `no_settings` (the run had no print settings), `too_many_triangles` (the model is over `max_triangles`)
    or `no_printed_parts` (every part is a `reference`). `bed_fit_skipped` is `no_bed` when no bed size is known. A gap
    too small to print open or to pull support out of is a failed check, `print_gap:<part>` or
    `print_trapped_support:<part>`, among the report's checks."""

    skip_reason: PrintSkipped | None
    printed: list[ReportPrintPart]
    bed_fit_skipped: Literal["no_bed"] | None
    max_triangles: int | None


class RunReport(BaseModel):
    """What a model script reported (`out/report.json`), all lengths in millimetres: its parts, the mesh's `triangles`,
    its checks and the pairs of parts that `overlaps`. `overlap_parts_skipped` counts the shown parts too many to compare.
    `print` is what the print check found, null for a run of a helper that had none."""

    parts: list[ReportPart]
    triangles: int
    checks: list[ReportCheck]
    overlaps: list[ReportOverlap]
    overlap_parts_skipped: int
    print: ReportPrint | None


def artifact_of(household_id: int, artifact: Artifact, key: bytes, now: float | None = None) -> RunArtifact:
    """The artifact and, when `key` is not empty, a link to it ending with the current half-`link_ttl_s` window."""
    if not key:
        return RunArtifact(name=artifact.name, size_bytes=artifact.size, media_type=artifact.media_type, url=None,
                           expires_at=None)
    ends = links.window_end(time.time() if now is None else now, CONFIG.link_ttl_s)
    link = links.mint(key, links.Grant(household_id, artifact.sha256, artifact.media_type, False, ends))
    return RunArtifact(name=artifact.name, size_bytes=artifact.size, media_type=artifact.media_type, url=link.url,
                       expires_at=link.expires_at)


def overlap_of_wire(o: Overlap) -> ReportOverlap:
    return ReportOverlap(a=o.a, b=o.b, volume_mm3=o.volume_mm3, bbox_min=list(o.bbox_min), bbox_max=list(o.bbox_max))


def _island_of_wire(i: Island) -> ReportIsland:
    return ReportIsland(bbox_min=list(i.bbox_min), bbox_max=list(i.bbox_max), area_mm2=i.area_mm2,
                        min_gap_mm=i.min_gap_mm, median_gap_mm=i.median_gap_mm)


def _print_part_of_wire(p: PrintPart) -> ReportPrintPart:
    return ReportPrintPart(name=p.name, bed_z=p.bed_z, support_area_mm2=p.support_area_mm2, bed_contact_mm2=p.bed_contact_mm2,
                           fits_bed=p.fits_bed, islands=[_island_of_wire(i) for i in p.islands],
                           islands_total=p.islands_total)


def print_of_wire(p: PrintCheck) -> ReportPrint:
    return ReportPrint(skip_reason=p.skip_reason, printed=[_print_part_of_wire(part) for part in p.printed],
                       bed_fit_skipped=p.bed_fit_skipped, max_triangles=p.max_triangles)


def report_of_wire(report: ModelReport) -> RunReport:
    return RunReport(
        parts=[ReportPart(name=p.name, role=p.role, form=p.form, volume=p.volume, bbox_min=list(p.bbox_min),
                          bbox_max=list(p.bbox_max))
               for p in report.parts],
        triangles=report.triangles,
        checks=[ReportCheck(name=c.name, actual=c.actual, op=c.op, target=c.target, tolerance=c.tolerance,
                            rests_on=list(c.rests_on), verdict=c.verdict) for c in report.checks],
        overlaps=[overlap_of_wire(o) for o in report.overlaps], overlap_parts_skipped=report.overlap_parts_skipped,
        print=None if report.print is None else print_of_wire(report.print))
