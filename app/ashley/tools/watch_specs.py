"""What her watch tools look like to the model (`watches.WatchTools`): structured fields only. `kind` is an enum of the
kinds the person can use, and `until`'s fields are enumerated from those kinds' tracked fields."""

from collections.abc import Collection

from ..inference.model import ToolSpec
from ..watches.model import MAX_TARGET
from ..watches.tool_watch import NAME as TOOL
from . import watch_conditions, watch_read, watch_sort
from .reminder_shape import TOOLS

WATCH, UNWATCH, WATCHES = "watch", "unwatch", "watches"
WHEN = ("For kind tool: what wakes you, in the shape of until, over the fields read.track names (hash when it has no "
        "path). Left out, any change wakes you.")

INSTRUCTIONS = (
    "You can keep watch on something the person has connected and be woken when it changes, with no one asking you "
    "again: watch starts one on a target of a kind, and unwatch stops it by the kind and target you watched. Use it "
    "when they ask you to keep an eye on something, or to tell them when it finishes, closes or changes, and not for "
    "an event you are told of anyway. A target is named exactly as its source lists it (a session by the id "
    "claude_sessions gives). Without until you are woken for the kind's ordinary changes (a session finishing or "
    "blocking); with it, when that thing happens, once, and the watch then stops. Every watch ends at its time. A "
    "target the source does not list is refused: read the list first, and when nothing matches what they asked about "
    "say so and watch nothing. Watching reads the target once and needs no OK. Tell them what you are watching and "
    "until when only after the call has succeeded. watches lists the ones they have, with why any is paused.")
ACTING = (" A watch can do something when it wakes you instead of only telling them: name the tools in tools. That is "
          "a proposal: say in one plain line what it will do and with which tools, and it is set only after they "
          "agree in a later message with arm_reminder. A watch can carry a brief, which is all you will see of why it "
          "exists when it wakes you, and be standing, to go on while its source answers. To keep a mailbox sorted, watch "
          "its mail_inbox with a brief, standing, and tools that include mail_label. "
          "What you do on a wake goes by the same tiers as any turn that has read outside words: a label or a draft runs, "
          "a send or a move to the trash waits for the person's OK.")


def watch(kinds: Collection[str], tracked: Collection[str], max_hours: float, acting: bool) -> ToolSpec:
    """`kinds` are the ones the person can use, `tracked` their tracked fields, `acting` offers `tools`. Kind `tool`
    takes its target from `read` and its fields from `read.track`, so then `until`'s fields are not enumerated."""
    reads = TOOL in kinds
    fields = None if reads else tracked
    return ToolSpec(WATCH, "Start watching a target: you read it now, and are woken when it changes (or, with until, "
                    "when that happens), until it ends or its time runs out. Returns what it reads now and when it "
                    "ends, or for a watch that acts a proposal to tell them, which is not set until they agree.", {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": sorted(kinds)},
                            "target": {"type": "string", "maxLength": MAX_TARGET,
                                       "description": "what to watch; for a session its id from claude_sessions"},
                            **({"read": watch_read.READ, "when": watch_conditions.schema(None, WHEN)} if reads else {}),
                            "until": watch_conditions.schema(fields),
                            "hours": {"type": "number", "minimum": 1, "maximum": max_hours,
                                      "description": "how long to watch at most; the kind's usual time if left out"},
                            **watch_sort.PROPERTIES,
                            **({"tools": TOOLS} if acting else {}),
                        },
                        "required": ["kind"] if reads else ["kind", "target"],
                    }, outside=True, tier="runs", label="Started watching something")


def unwatch(kinds: Collection[str]) -> ToolSpec:
    return ToolSpec(UNWATCH, "Stop watching a target, by the kind and target you started it with.", {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": sorted(kinds)},
                       "target": {"type": "string", "maxLength": MAX_TARGET,
                                  "description": "the target exactly as watches lists it, never its label; for a "
                                                 "session its id"}},
        "required": ["kind", "target"]}, outside=False, tier="runs", label="Stopped watching something")


WATCHES_SPEC = ToolSpec(WATCHES, "List the things you are watching for the person you are talking with, soonest ending "
                        "first, with what ends each and, for a paused one, why it paused.",
                        {"type": "object", "properties": {}}, reads=True, outside=False)
