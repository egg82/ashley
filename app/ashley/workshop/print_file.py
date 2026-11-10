"""The print settings a model run starts with, `print.json`, which the CAD helper's print check reads
(`deploy/cad/ashley_print.py`, whose tests run against this file): its thresholds and the closed list of part roles a
script may give `show`. Nothing in it is a household's; `bed_mm` ships null, so bed fit is reported as skipped."""

import json
from pathlib import Path

FILE = Path(__file__).with_name("print.json")
NAME = "print.json"


def file_text() -> str:
    """The settings as the run is given them."""
    return json.dumps(json.loads(FILE.read_text(encoding="utf-8")), separators=(",", ":"))
