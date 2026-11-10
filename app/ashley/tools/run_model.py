"""What a model run adds to the result she is given: the binary files it made (by name, type and size, no link, since her
tools hold no link key and a link lasts minutes; the person's page has the downloads) and its report with the app's
verdict on each check. Nothing for a run that has neither, so any other run's result is unchanged."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict

from ..runs.model import Artifact, Output
from ..workshop.model_report import report_of


def extras(artifacts: Sequence[Artifact], output: Output, inputs: Mapping[str, str]) -> dict[str, object]:
    """`artifacts` and `report` for the result of a run with `output`, started with `inputs`; empty when it left neither."""
    found: dict[str, object] = {}
    if artifacts:
        found["artifacts"] = [{"name": a.name, "media_type": a.media_type, "size_bytes": a.size} for a in artifacts]
    report = report_of(output, inputs)
    if report is not None:
        found["report"] = asdict(report)
    return found
