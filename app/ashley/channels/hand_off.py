"""The one nudge a long bench turn gets toward `bench_hand_off`: past `Limits.hand_off_after_s` of its window or
`hand_off_after_rounds` rounds, with the tool offered, the loop adds `unsaid.HAND_OFF` to its entries, once. The tool
choice stays `auto`: the model decides, code only makes sure it was told. A turn already asked again after a step was cut
off (`channels.cutoff`, `Steps.cut_off`) is not told: that note named the tool, where it was offered."""

from collections.abc import Mapping, Sequence

from ..inference.model import Entry, Prompt, SystemPrompt, ToolChoice, ToolSpec
from . import unsaid
from .pace import Pace

TOOL = "bench_hand_off"


def offered(tools: Sequence[ToolSpec]) -> bool:
    """Whether `bench_hand_off` is among `tools`."""
    return any(t.name == TOOL for t in tools)


def due(entries: Sequence[Entry], tools: Sequence[ToolSpec], pace: Pace, rounds: int, cut_off: int) -> bool:
    """Whether the turn is past either limit, offers the tool, and has not been told yet, nor asked again after a cut-off
    (`cut_off`, the turn's count of those)."""
    limits = pace.limits
    if not offered(tools) or unsaid.HAND_OFF in entries or cut_off:
        return False
    return (0 < limits.hand_off_after_s and pace.past(limits.hand_off_after_s)) or 0 < limits.hand_off_after_rounds <= rounds


def step_prompt(system: Mapping[str, SystemPrompt], entries: list[Entry], tools: tuple[ToolSpec, ...],
                asked: tuple[ToolChoice, int, bool], at: tuple[Pace, int, int]) -> Prompt:
    """A fresh step's prompt as `unsaid.step_prompt` shapes it (`asked`: its tool choice, the calls so far and whether it
    carries the act note); under `auto`, `unsaid.HAND_OFF` is first added to `entries` when `due` at `at` (the turn's
    pace, round and cut-off count)."""
    choice, calls, acting = asked
    if choice == "auto" and due(entries, tools, *at):
        entries.append(unsaid.HAND_OFF)
    return unsaid.step_prompt(system, entries, tools, choice, calls, acting)
