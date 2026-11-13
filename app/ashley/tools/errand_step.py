"""The one tool a check of an errand offers (`channels.turn_tools`, for a turn whose `Inbound.errand` is set):
`check_again` sets when she looks next and what she notes for then (`ashley.senses.wakes.Wakes.follow_up`). Left
uncalled, the errand ends with this check. Its limits are data, `errand.json` beside this module: `min_gap_minutes`
between checks, and `max_hours`, the longest an errand may run from its first check, which `remind` reads. Logs
`tools.call` with the outcome and the next check's wake id, never the plan."""

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import services
from ..inference.model import ToolCall, ToolResult, ToolSpec
from ..senses.wakes import MAX_BRIEF, Wakes, WakesUnavailable
from . import bench_results
from .bench_args import BadArguments, check_names
from .tools import Catalogue, Tools

FILE = Path(__file__).with_name("errand.json")
CHECK_AGAIN = "check_again"


@dataclass(frozen=True)
class ErrandConfig:
    min_gap_minutes: int
    max_hours: float


def load() -> ErrandConfig:
    """The limits shipped in `errand.json`. Raises ValueError when one is missing, unknown or not positive."""
    raw = json.loads(FILE.read_text())
    if set(raw) != set(ErrandConfig.__dataclass_fields__):
        raise ValueError(f"errand.json has exactly {sorted(ErrandConfig.__dataclass_fields__)}")
    made = ErrandConfig(int(raw["min_gap_minutes"]), float(raw["max_hours"]))
    if made.min_gap_minutes <= 0 or made.max_hours <= 0:
        raise ValueError("errand limits must be positive")
    return made


CONFIG = load()

SPEC = ToolSpec(CHECK_AGAIN, "Set when you look at this errand again and what you note for then; at that check you "
                "see only the ask and this plan. Not calling it ends the errand with this check. Returns how many "
                "minutes until the next check, or that none can be set (its end has come, or it was cancelled).", {
                    "type": "object",
                    "properties": {
                        "minutes": {"type": "integer", "minimum": CONFIG.min_gap_minutes,
                                    "maximum": int(CONFIG.max_hours * 60),
                                    "description": "how many minutes from now to look again"},
                        "plan": {"type": "string", "maxLength": MAX_BRIEF,
                                 "description": "what you have done and seen so far, and what to look at or try next"},
                    },
                    "required": ["minutes", "plan"],
                }, outside=False, tier="runs", label="Set the errand's next check")
INSTRUCTIONS = ("This turn is one check of an errand. When it is not done and there is still time, call check_again "
                "with when to look next and what you have done and seen; otherwise let it end and say how it went.")


class ErrandStepTools(Tools):
    def __init__(self, household_id: int, wake_id: int) -> None:
        """For the check that is occurrence `wake_id` of the household's errand."""
        self._household_id, self._wake_id = household_id, wake_id

    async def catalogue(self) -> Catalogue:
        return Catalogue((SPEC,), INSTRUCTIONS)

    async def call(self, call: ToolCall) -> ToolResult:
        """Never raises: an unknown tool, a bad argument, an errand that has ended or the store out of reach is an error
        result."""
        started = time.monotonic()
        if call.name != CHECK_AGAIN:
            return bench_results.failed(call, started, "unknown_tool", f"no tool named {call.name}")
        try:
            minutes, plan = _arguments(call)
            made = await services.get(Wakes).follow_up(self._household_id, self._wake_id,
                                                       datetime.now(UTC) + timedelta(minutes=minutes), plan)
        except BadArguments as e:
            return bench_results.failed(call, started, "bad_arguments", str(e))
        except WakesUnavailable:
            return bench_results.failed(call, started, "unavailable", "the errand cannot be reached right now")
        if made is None:
            return bench_results.failed(call, started, "ended", "no next check can be set: its end has come or it was "
                                        "cancelled; tell them how it went", wake=self._wake_id)
        return bench_results.ok(call, started, {"next_in_minutes": minutes}, wake=made)


def _arguments(call: ToolCall) -> tuple[int, str]:
    args = call.arguments
    check_names(args, SPEC)
    minutes, plan = args.get("minutes"), args.get("plan")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or not (
            CONFIG.min_gap_minutes <= minutes <= CONFIG.max_hours * 60):
        raise BadArguments(f"minutes is a whole number from {CONFIG.min_gap_minutes} to {int(CONFIG.max_hours * 60)}")
    if not isinstance(plan, str) or not plan.strip() or len(plan) > MAX_BRIEF or "\x00" in plan:
        raise BadArguments(f"plan is what you have done and seen, 1 to {MAX_BRIEF} characters")
    return minutes, plan
