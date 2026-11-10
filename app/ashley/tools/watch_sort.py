"""The arguments of `watch` that make a watch a sort (`decisions.md`, "The inbox watch and the sort"): its `brief`, whether
and whether it is `standing`. Shapes only: a bad one raises `BadArguments` naming the argument, never its value."""

from collections.abc import Mapping

from ..watches.model import MAX_BRIEF
from .bench_args import BadArguments

PROPERTIES: dict[str, dict[str, object]] = {
    "brief": {"type": "string", "maxLength": MAX_BRIEF,
              "description": "what each wake of this watch is for, in your words: you will see only this when it "
                             "wakes you"},
    "standing": {"type": "boolean",
                 "description": "true keeps the watch going for as long as its source answers, until it is stopped "
                                "with unwatch; each read that works moves its end forward by hours"}}


def brief(args: Mapping[str, object]) -> str | None:
    raw = args.get("brief")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_BRIEF or "\x00" in raw:
        raise BadArguments(f"brief is 1 to {MAX_BRIEF} characters")
    return raw.strip()


def standing(args: Mapping[str, object]) -> bool:
    raw = args.get("standing", False)
    if not isinstance(raw, bool):
        raise BadArguments("standing is true or false")
    return raw

