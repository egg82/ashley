"""`bench_look`'s optional arguments, as the model sent them: `region`, the part of the picture to look at, and `view`,
the side of a model to look from. Raises BadArguments, naming the argument and never its value."""

import math
from collections.abc import Mapping
from typing import Any

from ..looks import pictures
from ..looks.pictures import Region
from ..looks.views import VIEWS
from .bench_args import BadArguments

REGION_KEYS = ("x", "y", "w", "h")


def region_of(args: Mapping[str, object], minimum: float) -> Region | None:
    """The `region` argument, None when absent: an object of exactly `x`, `y`, `w`, `h`, fractions of the picture that
    lie inside it and are each side at least `minimum`."""
    if "region" not in args:
        return None
    loose: Any = args["region"]
    if not isinstance(args["region"], dict):
        raise BadArguments("region is an object of x, y, w and h")
    given = dict[object, object](loose)
    if sorted(str(k) for k in given) != sorted(REGION_KEYS):
        raise BadArguments("region is an object of x, y, w and h")
    numbers: dict[str, float] = {}
    for key in REGION_KEYS:
        value = given[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BadArguments(f"region.{key} is a number")
        numbers[key] = float(value)
    region = Region(numbers["x"], numbers["y"], numbers["w"], numbers["h"])
    try:
        pictures.check_region(region, minimum)
    except ValueError as e:
        raise BadArguments(str(e)) from e
    return region


def view_of(args: Mapping[str, object]) -> str | None:
    """The `view` argument, None when absent: one of `VIEWS`."""
    if "view" not in args:
        return None
    value = args["view"]
    if not isinstance(value, str) or value not in VIEWS:
        raise BadArguments(f"view is one of {', '.join(VIEWS)}")
    return value
